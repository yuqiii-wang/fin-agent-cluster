"""TaskRunnerMixin — task execution and LangChain Runnable wrapping."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableLambda

from backend.langgraph.lifecycle import make_task_id
from backend.langgraph.models.models import NodeContext, TaskContext, TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask


class TaskRunnerMixin:
    """Mixin for executing NodeTask functions inside a node.

    Methods:
        run_task          : Stamps a TaskContext and invokes the @task fn.
        _task_as_runnable : Wraps a NodeTask as a LangChain RunnableLambda.
    """

    async def run_task(
        self,
        node_task: NodeTask,
        ctx: NodeContext,
        content: Any,
    ) -> TaskOutput:
        """Build TaskInput envelope and invoke the @task fn.

        Stamps a fresh ``task_id``, appends it to ``ctx.task_ids``, and
        invokes the task function.  If a paused task for this (node_id,
        task_name) exists from a prior run, its ``task_id`` is reused so
        :func:`~backend.celery_task.workers.task_delegation.delegate_stream`
        can locate the saved snapshot and dispatch compact_and_continue.

        Args:
            node_task: The ``NodeTask`` whose ``task_fn`` to invoke.
            ctx:       Current node context — mutated to record the task_id.
            content:   Typed biz input; must match ``node_task.input_type``.

        Returns:
            ``TaskOutput`` with the same ``TaskContext`` and typed content.
        """
        from backend.langgraph.lifecycle.threads.nodes.tasks.ops import (
            get_existing_task_for_node,
            get_task_full,
            reset_task_for_retry,
        )
        from backend.langgraph.lifecycle.pause_flag import clear_task_pause_flag

        existing = await get_existing_task_for_node(ctx.thread_id, ctx.node_id, node_task.name)
        # Guard against returning a cached result from a *different* parallel invocation of the
        # same task within this node (e.g. prepare_index running get_and_calculate_stats for N
        # symbols concurrently).  ctx.task_ids is appended to before the @task fn is awaited, so
        # if task_id is already present another coroutine has claimed it; create a fresh one.
        existing_claimed = existing is not None and existing["task_id"] in ctx.task_ids
        if existing and not existing_claimed and existing["status"] == "completed":
            # Task was already completed by _run_retry_background; reuse the stored
            # output without re-running so the resumed graph can reach complete_node.
            task_id = existing["task_id"]
            task_row = await get_task_full(ctx.thread_id, task_id)
            output_data = task_row.get("output") if task_row else None
            if output_data is not None:
                ctx.task_ids.append(task_id)
                task_ctx = TaskContext(
                    **ctx.model_dump(),
                    task_id=task_id,
                    task_name=node_task.name,
                )
                # Streaming tasks store output wrapped in StreamingTaskOutput
                # {"thinking": ..., "answer": {...}}.  Unwrap to get the
                # task-specific result dict before validating.
                raw = output_data.get("answer", output_data) if isinstance(output_data.get("answer"), dict) else output_data
                return TaskOutput(
                    ctx=task_ctx,
                    content=node_task.output_type.model_validate(raw),
                )
            # output is missing; reset and re-run normally.
            await reset_task_for_retry(ctx.thread_id, task_id)
        elif existing and not existing_claimed and existing["status"] in ("paused", "failed"):
            task_id = existing["task_id"]
            await reset_task_for_retry(ctx.thread_id, task_id)
            if existing["status"] == "paused":
                await clear_task_pause_flag(task_id)
        else:
            task_id = make_task_id()
        ctx.task_ids.append(task_id)
        task_ctx = TaskContext(
            **ctx.model_dump(),
            task_id=task_id,
            task_name=node_task.name,
        )
        result = await node_task.task_fn(TaskInput(ctx=task_ctx, content=content))
        # LangGraph @task may return a checkpoint-cached result where the generic
        # TaskOutput[T].content was deserialized as a plain dict instead of the
        # concrete Pydantic model.  Re-validate here to guarantee callers always
        # receive a typed model instance.
        if isinstance(result.content, dict):
            raw = result.content.get("answer", result.content) if isinstance(result.content.get("answer"), dict) else result.content
            result = TaskOutput(ctx=result.ctx, content=node_task.output_type.model_validate(raw))
        return result

    def _task_as_runnable(self, task: NodeTask, ctx: NodeContext) -> RunnableLambda:
        """Wrap a NodeTask as a LangChain ``RunnableLambda`` chain step.

        Args:
            task: The NodeTask to wrap.
            ctx:  Current node context passed through to ``run_task``.

        Returns:
            A ``RunnableLambda`` that invokes ``run_task`` asynchronously.
        """
        async def _step(content: Any) -> TaskOutput:
            return await self.run_task(task, ctx, content)  # type: ignore[attr-defined]

        return RunnableLambda(_step)


__all__ = ["TaskRunnerMixin"]
