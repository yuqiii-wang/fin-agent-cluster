"""BaseNode and ChildNode — the agent-ready node template.

Design: node as agent contract
-------------------------------
Every node exposes these methods that together define its contract:

    build_input(state)      — reads typed input from predecessor outputs via DB
    build_chain(ctx)        — composes task steps into a Runnable chain (agent loop later)
    build_output(results)   — selects / composes from task outputs for the node output
    get_state_updates(out)  — maps node output to GraphState key updates (usually {})

The ``build_chain`` method is the seam for the agent upgrade:

    Chain flow (current):
        Compose ``_task_as_runnable`` steps using LangChain operators::

            Sequential:   step_a | step_b | collect
            Parallel:     RunnableParallel(a=step_a, b=step_b) | merge | collect
            Pass-through: RunnablePassthrough.assign(key=step) to extend a
                          dict while preserving prior keys.

    Agent mode (future override):
        Return a ``RunnableLambda`` wrapping a LangChain ReAct agent that
        uses ``self.tasks`` as tools.  The ``dict[str, TaskOutput]``
        output contract for ``build_output`` is unchanged.

Lifecycle
---------
``__call__``              — top-level LangGraph entrypoint (enters + orchestrates + exits)
``_run_as_child``         — called by a parent subgraph; same lifecycle but with
                            ``parent_node_id`` and optional ``parallel_group``.
``run_task``              — stamps a fresh TaskContext and invokes the @task fn.
``_task_as_runnable``     — wraps a NodeTask as a ``RunnableLambda`` chain step.

Fork versioning
---------------
``__call__`` reads ``state.get("fork_generation", 1)`` to determine the
version for this branch.  The node_id is UUID5(thread_id, node_name, version)
ensuring forked nodes are distinct from original-run nodes.

Node output data flow
---------------------
Node inputs/outputs are NOT passed through GraphState.  Instead:
- Inputs are written to ``fin_agents.node_executions`` via ``upsert_node``.
- Outputs are written to ``fin_agents.node_executions`` via ``complete_node``.
- Downstream nodes read predecessor output via ``read_node_output(node_id)``
  (which queries the PG replica).
This keeps checkpoint blobs small and reduces primary DB load.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Generic, TypeVar

from langchain_core.runnables import Runnable, RunnableLambda

from backend.langgraph.state import GraphState, NodeRecord
from backend.db.postgres.types import NodeType
from backend.langgraph.lifecycle import (
    complete_node,
    get_latest_sibling_node_version,
    make_node_id,
    make_task_id,
    upsert_node,
)
from backend.langgraph.nodes.base.models import NodeContext, TaskContext, TaskInput, TaskOutput
from backend.langgraph.nodes.base.task import NodeTask

I = TypeVar("I")
O = TypeVar("O")

logger = logging.getLogger(__name__)


class BaseNode(ABC, Generic[I, O]):
    """Template for all LangGraph nodes — fixed-flow now, agent-upgradeable later.

    Class variables:
        node_name: Registered node name; used in DB rows and SSE events.
        node_type: ``NodeType.WORKFLOW`` or ``NodeType.SUBGRAPH``.
        tasks: Ordered list of ``NodeTask`` instances.  In agent mode this
            becomes the tool registry surfaced to the LLM.
        _prev_node_names: List of predecessor node names in the graph.
            Used to resolve prev_node_ids from the current state.
        parallel_group: Optional shared label that groups all nodes executing
            concurrently within the same parent scope.  Set this on every
            top-level node that participates in a fan-out / fan-in.
        parallel_branch: Optional branch identity within the parallel_group.
            Defaults to ``node_name`` when ``parallel_group`` is set.
            For multi-node sequential chains within a branch, set this to the
            same value on every node in the chain.
    """

    node_name: ClassVar[str]
    node_type: ClassVar[NodeType]
    tasks: ClassVar[list[NodeTask]]
    _prev_node_names: ClassVar[list[str]] = []
    parallel_group: ClassVar[str | None] = None
    parallel_branch: ClassVar[str | None] = None

    @staticmethod
    def _find_node_id_by_name(state: GraphState, node_name: str) -> str | None:
        """Look up a node_id from the current nodes dict by node_name.

        Scans ``state["nodes"]`` for a record whose metadata.node_name matches.
        Used by downstream nodes to find their predecessor's node_id so they
        can call ``read_node_output(node_id)``.

        Args:
            state:     Current GraphState.
            node_name: The ``node_name`` to search for.

        Returns:
            The matching node_id string, or ``None`` if not found.
        """
        for node_id, record in (state.get("nodes") or {}).items():
            meta = record.get("metadata") or {}
            if meta.get("node_name") == node_name:
                return node_id
        return None

    @abstractmethod
    async def build_input(self, state: GraphState) -> I:
        """Construct typed node input from predecessor outputs in the DB.

        Reads predecessor node output via ``read_node_output(node_id)``
        (which queries the PG replica) rather than from GraphState blobs.
        Returns a fully-typed input model.
        """

    @abstractmethod
    def build_chain(self, ctx: NodeContext) -> Runnable[I, dict[str, TaskOutput]]:
        """Compose the node's task steps into a LangChain ``Runnable`` chain."""

    async def orchestrate(
        self, ctx: NodeContext, node_input: I
    ) -> dict[str, TaskOutput]:
        """Execute the node's chain and return keyed task results."""
        return await self.build_chain(ctx).ainvoke(node_input)

    @abstractmethod
    def build_output(self, results: dict[str, TaskOutput]) -> O:
        """Select and compose node output from task results."""

    @abstractmethod
    def get_state_updates(self, output: O) -> dict[str, Any]:
        """Map node output to GraphState key → value updates.

        Most nodes return ``{}`` since data flows via DB, not state.
        ``conclusion_node`` returns ``{"conclusion": output.answer}`` so
        ``executor.py`` can read it from ``final_state``.
        """

    async def run_task(
        self,
        node_task: NodeTask,
        ctx: NodeContext,
        content: Any,
    ) -> TaskOutput:
        """Build TaskInput envelope and invoke the @task fn.

        Stamps a fresh ``task_id``, appends it to ``ctx.task_ids``, and
        invokes the task function.

        Args:
            node_task: The ``NodeTask`` whose ``task_fn`` to invoke.
            ctx:       Current node context — mutated to record the task_id.
            content:   Typed biz input; must match ``node_task.input_type``.

        Returns:
            ``TaskOutput`` with the same ``TaskContext`` and typed content.
        """
        task_id = make_task_id()
        ctx.task_ids.append(task_id)
        task_ctx = TaskContext(
            **ctx.model_dump(),
            task_id=task_id,
            task_name=node_task.name,
        )
        return await node_task.task_fn(TaskInput(ctx=task_ctx, content=content))

    def _task_as_runnable(self, task: NodeTask, ctx: NodeContext) -> RunnableLambda:
        """Wrap a NodeTask as a LangChain ``RunnableLambda`` chain step."""
        async def _step(content: Any) -> TaskOutput:
            return await self.run_task(task, ctx, content)

        return RunnableLambda(_step)

    def _build_node_record(
        self,
        node_id: str,
        version: int,
        prev_node_ids: list[str],
        status: str,
    ) -> NodeRecord:
        """Build a NodeRecord dict for insertion into ``GraphState.nodes``."""
        return NodeRecord(
            node_id=node_id,
            task_ids=[],
            metadata={
                "node_name": self.node_name,
                "type": str(self.node_type),
                "status": status,
                "version": version,
            },
            prev_node_ids=prev_node_ids,
            next_node_ids=[],
        )

    async def _run_as_child(
        self,
        parent_ctx: NodeContext,
        node_input: I,
        parallel_group: str | None = None,
        parallel_branch: str | None = None,
    ) -> O:
        """Run this node as a child within a parent subgraph.

        Inherits ``version`` from ``parent_ctx`` so child nodes belong to
        the same fork branch as their parent.

        Args:
            parent_ctx:      The parent subgraph's NodeContext.
            node_input:      Typed input — constructed by the parent, not from state.
            parallel_group:  Optional label grouping sibling parallel nodes.
            parallel_branch: Optional branch identity within the parallel_group.
                Defaults to ``self.node_name`` when ``parallel_group`` is set.

        Returns:
            Typed node output (``O``).
        """
        thread_id = parent_ctx.thread_id
        version = parent_ctx.version
        node_id = make_node_id(thread_id, self.node_name, version)
        effective_branch = parallel_branch or (self.node_name if parallel_group else None)
        ctx = NodeContext(
            thread_id=thread_id,
            node_id=node_id,
            node_name=self.node_name,
            version=version,
            prev_node_ids=[parent_ctx.node_id],
        )
        await upsert_node(
            thread_id=thread_id,
            node_id=node_id,
            node_name=self.node_name,
            node_type=self.node_type,
            parent_node_id=parent_ctx.node_id,
            input_data=node_input.model_dump(),
            parallel_group=parallel_group,
            parallel_branch=effective_branch,
            version=version,
            prev_node_ids=[parent_ctx.node_id],
        )
        try:
            results = await self.orchestrate(ctx, node_input)
        except Exception as exc:
            await complete_node(
                thread_id=thread_id,
                node_id=node_id,
                node_name=self.node_name,
                failed=True,
                error=str(exc),
            )
            raise
        node_output = self.build_output(results)
        await complete_node(
            thread_id=thread_id,
            node_id=node_id,
            node_name=self.node_name,
            output_data=node_output.model_dump(),
        )
        return node_output

    async def _cancel_self_and_cascade(
        self,
        thread_id: str,
        node_id: str,
        version: int,
        prev_node_ids: list[str],
        reason: str,
    ) -> GraphState:
        """Cancel this node in the lifecycle layer and cascade to the thread if needed.

        Called when a merge/join node detects that one of its required
        predecessors was cancelled.  Performs:
        1. ``cancel_node`` — DB + SSE (node is already 'running' from upsert_node).
        2. Thread-level cascade — if no active top-level nodes remain, cancels
           the thread (sets Redis cancel flag + DB status).
        3. Returns a ``cancelled`` state delta so LangGraph can finish the
           graph cleanly without raising.

        Args:
            thread_id:      LangGraph thread UUID.
            node_id:        This node's stable ID.
            version:        Fork generation counter.
            prev_node_ids:  Predecessor node IDs.
            reason:         Cancellation reason label.

        Returns:
            GraphState delta with this node marked ``cancelled``.
        """
        from backend.db.postgres import raw_conn
        from backend.langgraph.lifecycle import cancel_node as _lc_cancel_node
        from backend.langgraph.lifecycle import cancel_thread as _lc_cancel_thread
        from backend.main_thread.cancel_flag import set_cancel_flag

        # 1. Cancel in lifecycle (DB → 'cancelled', SSE emitted).
        try:
            await _lc_cancel_node(thread_id, node_id, reason=reason)
        except Exception as exc:
            logger.error(
                "[base_node] auto-cancel DB failed node_id=%s reason=%s: %s",
                node_id, reason, exc,
            )

        # 2. Thread-level cascade: if no active top-level nodes remain, cancel thread.
        try:
            async with raw_conn(readonly=True) as conn:
                cur = await conn.execute(
                    "SELECT COUNT(*) AS cnt FROM fin_agents.nodes "
                    "WHERE thread_id = %s AND parent_node_id IS NULL "
                    "AND status NOT IN ('completed','failed','cancelled','wrong')",
                    (thread_id,),
                )
                row = await cur.fetchone()
            if (row["cnt"] if row else 1) == 0:
                await set_cancel_flag(thread_id)
                await _lc_cancel_thread(thread_id, reason=reason)
        except Exception as exc:
            logger.error(
                "[base_node] auto-cancel cascade failed thread_id=%s: %s",
                thread_id, exc,
            )

        # 3. Return cancelled state delta — do not raise.
        cancelled_record = self._build_node_record(node_id, version, prev_node_ids, "cancelled")
        return {"nodes": {node_id: cancelled_record}}

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
        from backend.langgraph.lifecycle.errors import NodeCancelledError

        thread_id: str = state["thread_id"]
        version: int = state.get("fork_generation", 0)  # type: ignore[assignment]
        node_id = make_node_id(thread_id, self.node_name, version)

        # Detect whether this node is the fork-point of a re-explore branch.
        is_forked: bool = state.get("fork_point_node_name") == self.node_name and version > 0
        forked_from_version: int | None = state.get("fork_source_version") if is_forked else None

        # Resolve predecessor node IDs from the current nodes dict.
        prev_node_ids: list[str] = [
            nid
            for name in self._prev_node_names
            if (nid := self._find_node_id_by_name(state, name)) is not None
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
            and self.parallel_group == fork_parallel_group
            and self.node_name != state.get("fork_point_node_name")
        ):
            # Find the latest completed version of this sibling node — NOT
            # bounded by fork_source_version (which tracks the fork-point
            # node's version history, not this sibling's).  E.g. if stats was
            # re-explored to v1, and then news is re-explored (fork_source_version=0
            # because news was at v0), we must use stats_v1, not stats_v0.
            sibling_version = await get_latest_sibling_node_version(
                thread_id, self.node_name
            )
            sibling_node_id = make_node_id(thread_id, self.node_name, sibling_version)
            shared_record = self._build_node_record(sibling_node_id, sibling_version, [], "completed")
            return {"nodes": {sibling_node_id: shared_record}}

        ctx = NodeContext(
            thread_id=thread_id,
            node_id=node_id,
            node_name=self.node_name,
            version=version,
            prev_node_ids=prev_node_ids,
        )

        node_input = await self.build_input(state)

        await upsert_node(
            thread_id=thread_id,
            node_id=node_id,
            node_name=self.node_name,
            node_type=self.node_type,
            input_data=node_input.model_dump(),
            version=version,
            prev_node_ids=prev_node_ids,
            parallel_group=self.parallel_group,
            parallel_branch=self.parallel_branch,
            is_forked=is_forked,
            forked_from_version=forked_from_version,
        )

        # --- Parallel-cancel check: auto-cancel merge nodes whose required
        # predecessors were cancelled (e.g. conclusion_node when one parallel
        # analysis branch was cancelled via the API).  This check runs after
        # upsert_node so the node row already exists in DB for cancel_node to update.
        for name in self._prev_node_names:
            for record in (state.get("nodes") or {}).values():
                meta = record.get("metadata") or {}
                if meta.get("node_name") == name and meta.get("status") == "cancelled":
                    logger.error(
                        "[base_node] predecessor '%s' is cancelled; auto-cancelling '%s' "
                        "thread_id=%s node_id=%s",
                        name, self.node_name, thread_id, node_id,
                    )
                    return await self._cancel_self_and_cascade(
                        thread_id, node_id, version, prev_node_ids,
                        reason="predecessor_cancelled",
                    )

        try:
            results = await self.orchestrate(ctx, node_input)
        except NodeCancelledError:
            # Node was externally cancelled via the API while executing.
            # The lifecycle layer (cancel_node) already updated DB + emitted SSE
            # and set the node to 'cancelled'.  Return a cancelled state delta so
            # LangGraph can complete the graph without raising, letting all other
            # parallel branches continue unaffected.
            cancelled_record = self._build_node_record(node_id, version, prev_node_ids, "cancelled")
            cancelled_record["task_ids"] = list(ctx.task_ids)
            return {"nodes": {node_id: cancelled_record}}
        except Exception as exc:
            # Mark node failed in DB and update NodeRecord status.
            await complete_node(
                thread_id=thread_id,
                node_id=node_id,
                node_name=self.node_name,
                failed=True,
                error=str(exc),
            )
            raise
        node_output = self.build_output(results)

        await complete_node(
            thread_id=thread_id,
            node_id=node_id,
            node_name=self.node_name,
            output_data=node_output.model_dump(),
        )

        # Update NodeRecord with completed status and accumulated task_ids.
        completed_record = self._build_node_record(node_id, version, prev_node_ids, "completed")
        completed_record["task_ids"] = list(ctx.task_ids)

        # Return only the delta — never spread the full state back.
        # Returning {**state, ...} causes INVALID_CONCURRENT_GRAPH_UPDATE when
        # two parallel nodes complete in the same step, because un-annotated
        # keys (thread_id, query, …) would receive two conflicting values.
        # The `nodes` key uses operator.or_ so it merges each node's single
        # NodeRecord dict correctly across parallel branches.
        state_updates = self.get_state_updates(node_output)
        return {"nodes": {node_id: completed_record}, **state_updates}


class ChildNode(BaseNode[I, O], ABC):
    """Base for nodes used exclusively as children within a subgraph.

    Subclasses must implement ``orchestrate``, ``build_output``, and
    ``get_state_updates``.  They must NOT be registered in the top-level
    LangGraph graph — use ``_run_as_child()`` from the parent instead.
    """

    async def build_input(self, state: GraphState) -> I:
        """Not applicable for child nodes."""
        raise NotImplementedError(
            f"{self.node_name!r} is a child-only node. "
            "Call _run_as_child() from the parent subgraph, not __call__()."
        )


__all__ = ["BaseNode", "ChildNode"]
