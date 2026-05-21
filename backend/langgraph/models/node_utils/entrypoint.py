"""EntrypointMixin — the LangGraph ``__call__`` implementation for BaseNode."""

from __future__ import annotations

import logging

from backend.langgraph.lifecycle import (
    complete_node,
    get_latest_sibling_node_version,
    make_node_id,
    upsert_node,
)
from backend.langgraph.models.models import NodeContext
from backend.langgraph.state import GraphState

logger = logging.getLogger(__name__)


class EntrypointMixin:
    """Mixin that implements the LangGraph ``__call__`` entrypoint for BaseNode.

    Methods:
        __call__ : Top-level LangGraph node invocation.
    """

    async def __call__(self, state: GraphState) -> GraphState:
        """LangGraph entrypoint.

        Reads fork_generation from state to determine the node's version and
        UUID5 node_id.  Builds NodeRecord for GraphState.nodes.  Wires:
        build_input(state) → upsert_node → orchestrate(ctx, inp)
        → build_output(results) → complete_node → state updates.

        If ``state["fork_point_node_name"]`` matches this node's name, marks
        the node as is_forked=TRUE in the DB (first node of a re-explore branch).

        Parallel-cancel semantics
        --------------------------
        Before orchestrating, checks whether any required predecessor node was
        cancelled (i.e. a parallel branch the graph barrier waited for).  If so,
        the node auto-cancels itself, cascades to the thread if no other active
        nodes remain, and returns a ``cancelled`` state delta without raising —
        so the other parallel branches and the join barrier complete cleanly.

        During orchestration, if a ``NodeCancelledError`` is raised (per-node
        cancel flag detected by ``_await_result``), the node was externally
        cancelled via the API.  Returns a ``cancelled`` state delta without
        raising so the other parallel branches continue unaffected.
        """
        from backend.langgraph.lifecycle.errors import NodeCancelledError, TaskPausedError

        thread_id: str = state["thread_id"]
        version: int = state.get("fork_generation", 0)  # type: ignore[assignment]
        node_id = make_node_id(thread_id, self.node_name, version)  # type: ignore[attr-defined]

        # Detect whether this node is the fork-point of a re-explore branch.
        is_forked: bool = state.get("fork_point_node_name") == self.node_name and version > 0  # type: ignore[attr-defined]
        forked_from_version: int | None = state.get("fork_source_version") if is_forked else None

        # Resolve predecessor node IDs from the current nodes dict.
        prev_node_ids: list[str] = [
            nid
            for name in self._prev_node_names  # type: ignore[attr-defined]
            if (nid := self._find_node_id_by_name(state, name)) is not None  # type: ignore[attr-defined]
        ]

        # Parallel sibling shortcut: when re-exploring a parallel group, a sibling
        # node (same group, not the fork point) must not re-run business logic.
        # It injects its prior-version NodeRecord back into state under the
        # original node_id so downstream nodes (e.g. conclusion_node) can
        # resolve the sibling's node_id via _find_node_id_by_name.  No new DB
        # record is created; the sibling is "shared" from the previous version.
        fork_parallel_group: str | None = state.get("fork_parallel_group")  # type: ignore[assignment]
        if (
            version > 0
            and fork_parallel_group is not None
            and self.parallel_group == fork_parallel_group  # type: ignore[attr-defined]
            and self.node_name != state.get("fork_point_node_name")  # type: ignore[attr-defined]
        ):
            # Find the latest completed version of this sibling node — NOT
            # bounded by fork_source_version (which tracks the fork-point
            # node's version history, not this sibling's).  E.g. if stats was
            # re-explored to v1, and then news is re-explored (fork_source_version=0
            # because news was at v0), we must use stats_v1, not stats_v0.
            sibling_version = await get_latest_sibling_node_version(
                thread_id, self.node_name  # type: ignore[attr-defined]
            )
            sibling_node_id = make_node_id(thread_id, self.node_name, sibling_version)  # type: ignore[attr-defined]
            shared_record = self._build_node_record(sibling_node_id, sibling_version, [], "completed")  # type: ignore[attr-defined]
            return {"nodes": {sibling_node_id: shared_record}}

        ctx = NodeContext(
            thread_id=thread_id,
            node_id=node_id,
            node_name=self.node_name,  # type: ignore[attr-defined]
            version=version,
            prev_node_ids=prev_node_ids,
        )

        node_input = await self.build_input(state)  # type: ignore[attr-defined]

        await upsert_node(
            thread_id=thread_id,
            node_id=node_id,
            node_name=self.node_name,  # type: ignore[attr-defined]
            node_type=self.node_type,  # type: ignore[attr-defined]
            input_data=node_input.model_dump(),
            version=version,
            prev_node_ids=prev_node_ids,
            parallel_group=self.parallel_group,  # type: ignore[attr-defined]
            parallel_branch=self.parallel_branch,  # type: ignore[attr-defined]
            is_forked=is_forked,
            forked_from_version=forked_from_version,
            view_type=self.view_type,  # type: ignore[attr-defined]
            view_schema=self.view_schema,  # type: ignore[attr-defined]
        )

        # --- Parallel-cancel check: auto-cancel merge nodes whose required
        # predecessors were cancelled (e.g. conclusion_node when one parallel
        # analysis branch was cancelled via the API).  This check runs after
        # upsert_node so the node row already exists in DB for cancel_node to update.
        for name in self._prev_node_names:  # type: ignore[attr-defined]
            for record in (state.get("nodes") or {}).values():
                meta = record.get("metadata") or {}
                if meta.get("node_name") == name and meta.get("status") == "cancelled":
                    logger.error(
                        "[base_node] predecessor '%s' is cancelled; auto-cancelling '%s' "
                        "thread_id=%s node_id=%s",
                        name, self.node_name, thread_id, node_id,  # type: ignore[attr-defined]
                    )
                    return await self._cancel_self_and_cascade(  # type: ignore[attr-defined]
                        thread_id, node_id, version, prev_node_ids,
                        reason="predecessor_cancelled",
                    )

        try:
            results = await self.orchestrate(ctx, node_input)  # type: ignore[attr-defined]
        except NodeCancelledError:
            # Node was externally cancelled via the API while executing.
            # The lifecycle layer (cancel_node) already updated DB + emitted SSE
            # and set the node to 'cancelled'.  Return a cancelled state delta so
            # LangGraph can complete the graph without raising, letting all other
            # parallel branches continue unaffected.
            cancelled_record = self._build_node_record(node_id, version, prev_node_ids, "cancelled")  # type: ignore[attr-defined]
            cancelled_record["task_ids"] = list(ctx.task_ids)
            return {"nodes": {node_id: cancelled_record}}
        except TaskPausedError:
            from backend.langgraph.lifecycle import pause_node as _pause_node
            await _pause_node(
                thread_id, node_id, self.node_name,  # type: ignore[attr-defined]
                is_last_paused_by_server=False,
            )
            raise
        except Exception as exc:
            # Mark node failed in DB and update NodeRecord status.
            await complete_node(
                thread_id=thread_id,
                node_id=node_id,
                node_name=self.node_name,  # type: ignore[attr-defined]
                failed=True,
                error=str(exc),
            )
            raise
        node_output = self.build_output(results)  # type: ignore[attr-defined]
        stored_output = (
            {"task_id": ctx.task_ids[-1]}
            if self.view_type == "Mirror" and ctx.task_ids  # type: ignore[attr-defined]
            else node_output.model_dump()
        )
        await complete_node(
            thread_id=thread_id,
            node_id=node_id,
            node_name=self.node_name,  # type: ignore[attr-defined]
            output_data=stored_output,
        )

        # Update NodeRecord with completed status and accumulated task_ids.
        completed_record = self._build_node_record(node_id, version, prev_node_ids, "completed")  # type: ignore[attr-defined]
        completed_record["task_ids"] = list(ctx.task_ids)

        # Return only the delta — never spread the full state back.
        # Returning {**state, ...} causes INVALID_CONCURRENT_GRAPH_UPDATE when
        # two parallel nodes complete in the same step, because un-annotated
        # keys (thread_id, query, …) would receive two conflicting values.
        # The `nodes` key uses operator.or_ so it merges each node's single
        # NodeRecord dict correctly across parallel branches.
        state_updates = self.get_state_updates(node_output)  # type: ignore[attr-defined]
        return {"nodes": {node_id: completed_record}, **state_updates}


__all__ = ["EntrypointMixin"]
