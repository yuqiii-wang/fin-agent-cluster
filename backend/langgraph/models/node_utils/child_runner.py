"""ChildRunnerMixin — running a node as a child within a parent subgraph."""

from __future__ import annotations

from typing import Any

from backend.langgraph.lifecycle import (
    complete_node,
    make_node_id,
    upsert_node,
)
from backend.langgraph.models.models import NodeContext


class ChildRunnerMixin:
    """Mixin providing ``_run_as_child`` for nodes embedded in a parent subgraph.

    Methods:
        _run_as_child : Execute this node within a parent's NodeContext.
    """

    async def _run_as_child(
        self,
        parent_ctx: NodeContext,
        node_input: Any,
        parallel_group: str | None = None,
        parallel_branch: str | None = None,
    ) -> Any:
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
            Typed node output.
        """
        from backend.langgraph.lifecycle.errors import TaskPausedError

        thread_id = parent_ctx.thread_id
        version = parent_ctx.version
        node_id = make_node_id(thread_id, self.node_name, version)  # type: ignore[attr-defined]
        effective_branch = parallel_branch or (self.node_name if parallel_group else None)  # type: ignore[attr-defined]
        ctx = NodeContext(
            thread_id=thread_id,
            node_id=node_id,
            node_name=self.node_name,  # type: ignore[attr-defined]
            version=version,
            prev_node_ids=[parent_ctx.node_id],
        )
        await upsert_node(
            thread_id=thread_id,
            node_id=node_id,
            node_name=self.node_name,  # type: ignore[attr-defined]
            node_type=self.node_type,  # type: ignore[attr-defined]
            parent_node_id=parent_ctx.node_id,
            input_data=node_input.model_dump(),
            parallel_group=parallel_group,
            parallel_branch=effective_branch,
            version=version,
            prev_node_ids=[parent_ctx.node_id],
            view_type=self.view_type,  # type: ignore[attr-defined]
            view_schema=self.view_schema,  # type: ignore[attr-defined]
        )
        try:
            results = await self.orchestrate(ctx, node_input)  # type: ignore[attr-defined]
        except TaskPausedError:
            from backend.langgraph.lifecycle import pause_node as _pause_node
            await _pause_node(
                thread_id, node_id, self.node_name,  # type: ignore[attr-defined]
                is_last_paused_by_server=False,
            )
            raise
        except Exception as exc:
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
        return node_output


__all__ = ["ChildRunnerMixin"]
