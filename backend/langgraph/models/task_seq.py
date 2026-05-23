"""TaskSeq — bundles a sequential pipeline of NodeTasks as a reusable unit.

A ``TaskSeq`` groups two or more :class:`~backend.langgraph.models.task.NodeTask`
instances into an ordered pipeline.  The individual tasks remain unchanged
at the Celery and DB persistence layers; the sequence only adds a thin
orchestration wrapper that feeds each task's output into the next.

Usage pattern
-------------
Declare in the hosting node's ``tasks`` ClassVar by spreading::

    tasks: ClassVar[list[NodeTask]] = [
        other_task,
        *my_seq.tasks,          # ← expand constituent NodeTasks
    ]

Execute via the pipeline in the node's chain / agent::

    result = await my_seq.run(
        self.run_task, ctx, MySeqInput(...)
    )

The ``pipeline_fn`` callable has signature::

    async def _pipeline(
        run_task_fn: Callable,
        ctx: NodeContext,
        seq_input: I,
    ) -> O: ...
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Generic, TypeVar

from pydantic import BaseModel

from backend.langgraph.models.models import NodeContext
from backend.langgraph.models.task import NodeTask

I = TypeVar("I")
O = TypeVar("O")


@dataclass
class TaskSeq(Generic[I, O]):
    """A sequential pipeline of NodeTasks executed as a single unit.

    Attributes:
        name:         Identifier for this sequence; used for logging and diagnostics.
        description:  Human-readable description.
        tasks:        Ordered list of constituent :class:`NodeTask` instances.
                      Spread into the hosting node's ``tasks`` ClassVar so that
                      Celery handler registration and agent-mode tool surfacing
                      include all constituent tasks.
        input_type:   Pydantic model type for the pipeline input.
        output_type:  Pydantic model type for the pipeline output.
        pipeline_fn:  Async function
                      ``(run_task_fn, ctx: NodeContext, seq_input: I) -> O``
                      that orchestrates the constituent tasks in order.
    """

    name: str
    description: str
    tasks: list[NodeTask]
    input_type: type[I]
    output_type: type[O]
    pipeline_fn: Callable[..., Awaitable[Any]]

    def __post_init__(self) -> None:
        """Validate that input_type and output_type are Pydantic BaseModel subclasses."""
        if not (isinstance(self.input_type, type) and issubclass(self.input_type, BaseModel)):
            raise TypeError(
                f"TaskSeq '{self.name}': input_type must be a Pydantic BaseModel subclass, "
                f"got {self.input_type!r}"
            )
        if not (isinstance(self.output_type, type) and issubclass(self.output_type, BaseModel)):
            raise TypeError(
                f"TaskSeq '{self.name}': output_type must be a Pydantic BaseModel subclass, "
                f"got {self.output_type!r}"
            )
        if not self.tasks:
            raise ValueError(f"TaskSeq '{self.name}': tasks list must not be empty.")

    async def run(
        self,
        run_task_fn: Callable[..., Awaitable[Any]],
        ctx: NodeContext,
        seq_input: I,
    ) -> O:
        """Execute the pipeline sequentially.

        Args:
            run_task_fn: Bound ``self.run_task`` from the hosting node.
            ctx:         Current node context.
            seq_input:   Typed pipeline input.

        Returns:
            Typed pipeline output produced by ``pipeline_fn``.
        """
        return await self.pipeline_fn(run_task_fn, ctx, seq_input)


__all__ = ["TaskSeq"]
