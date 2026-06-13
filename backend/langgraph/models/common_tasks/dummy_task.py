"""dummy_task -- placeholder NodeTask that runs until parent signals completion.

Useful for visually bracketing long-running operations in the UI without a real task
that are not Celery-dispatched. The task enters a 100-ms sleep loop and exits
only completes only when the parent sets an ``asyncio.Event`` in ``ctx.metadata``.

Usage
-----
From a seq should set ``ctx.metadata["dummy_task_signals"][overridden_name] = asyncio.Event()``
**before** calling ``run_task(dummy_task, ...)`` with ``DummyTaskInput(overridden_name="start_headless_browser")``;
then call ``.set()`` to signal completion. The task will observe the event
will exit and mark itself completed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pydantic import BaseModel, Field

from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask

logger = logging.getLogger(__name__)

_TASK_NAME = "dummy_task"


class DummyTaskInput(BaseModel):
    """Input for the dummy task.

    Attributes:
        overridden_name: Task name used when creating/completing the task row
                        (overrides the default ``"dummy_task"`` so the UI sees a
                        meaningful name).
        tick_sleep_secs:  Time to sleep between checks for the completion signal.
    """

    overridden_name: str = Field(
        default="dummy_task",
        description="Task name to use for lifecycle calls (may differ from NodeTask.name).",
    )
    tick_sleep_secs: float = Field(
        default=0.1,
        description="Seconds to sleep between checks for the completion signal.",
    )


class DummyTaskOutput(BaseModel):
    """Output from the dummy task."""

    tick_count: int = Field(default=0, description="Number of ticks observed before signal.")


async def _dummy_task_fn(
    task_input: TaskInput[DummyTaskInput],
) -> TaskOutput[DummyTaskOutput]:
    ctx = task_input.ctx
    inp = task_input.content

    overridden_name = inp.overridden_name or _TASK_NAME
    payload = inp.model_dump(mode="json")

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, overridden_name,
        payload,
        view_type="ToolCall",
    )

    try:
        signals: dict[str, Any] = ctx.metadata.setdefault("dummy_task_signals", {})
        signal: asyncio.Event = signals.get(overridden_name)

        tick_count = 0
        if signal is not None:
            while not signal.is_set():
                await asyncio.sleep(inp.tick_sleep_secs)
                tick_count += 1

        output = DummyTaskOutput(tick_count=tick_count)

        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, overridden_name,
            output_data=output.model_dump(mode="json"),
            view_type="ToolCall",
        )
        return TaskOutput(ctx=ctx, content=output)
    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, overridden_name,
            failed=True, error=str(exc), view_type="ToolCall",
        )
        raise


dummy_task: NodeTask[DummyTaskInput, DummyTaskOutput] = NodeTask(
    name=_TASK_NAME,
    description=(
        "Placeholder task that ticks in a sleep loop until the parent signals completion "
        "sets an ``asyncio.Event`` in ``ctx.metadata['dummy_task_signals'][overridden_name]``."
    ),
    input_type=DummyTaskInput,
    output_type=DummyTaskOutput,
    task_fn=_dummy_task_fn,
    handler=lambda payload: (_ for _ in ()).throw(
        NotImplementedError("dummy_task runs inside the graph runner directly."),
    ),
)

HANDLERS: dict = {}

__all__ = [
    "dummy_task",
    "DummyTaskInput",
    "DummyTaskOutput",
    "HANDLERS",
]
