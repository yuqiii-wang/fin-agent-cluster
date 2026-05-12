"""NodeTask — bundles a LangGraph @task fn with its Celery handler and metadata.

A ``NodeTask`` is the single unit of work that a node can perform.  It is
the bridge between two execution layers:

LangGraph layer (``task_fn``)
    The ``@task``-decorated async coroutine that runs inside the LangGraph
    thread.  It calls ``create_task``, delegates to Celery via
    ``delegate_completion`` / ``delegate_stream``, and returns a
    ``TaskOutput``.

Celery layer (``handler``)
    A pure async function ``(payload: dict) -> dict`` that contains the
    actual business logic.  Registered in the node's ``HANDLERS`` dict and
    dispatched to a worker process by the completion / stream Celery tasks.

Agent upgrade path
------------------
In agent mode, ``NodeTask`` becomes a LangChain ``StructuredTool``:

    tool = StructuredTool.from_function(
        coroutine=lambda inp: node.run_task(task, ctx, task.input_type(**inp)),
        name=task.name,
        description=task.description,
        args_schema=task.input_type,
    )

The node's ``orchestrate()`` override passes ``[t.as_tool(ctx) for t in self.tasks]``
to a ReAct / ToolNode agent.  The ``handler`` is unchanged — it still runs
in the Celery worker.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Generic, TypeVar

I = TypeVar("I")
O = TypeVar("O")


@dataclass
class NodeTask(Generic[I, O]):
    """A task that a node can execute.

    Attributes:
        name: Task name — key in the ``HANDLERS`` registry and ``fin_agents.tasks`` rows.
        description: Human-readable description; surfaced to the LLM as a tool description
            in agent mode.
        input_type: Pydantic model type for the task input content.
        output_type: Pydantic model type for the task output content.
        task_fn: The ``@task``-decorated async function (LangGraph orchestration layer).
        handler: Pure async handler ``(payload: dict) -> dict`` (Celery execution layer).
    """

    name: str
    description: str
    input_type: type[I]
    output_type: type[O]
    task_fn: Callable  # @task-decorated; awaited by BaseNode.run_task()
    handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


__all__ = ["NodeTask"]
