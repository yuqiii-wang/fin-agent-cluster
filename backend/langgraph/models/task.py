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

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Generic, TypeVar

from pydantic import BaseModel

I = TypeVar("I")
O = TypeVar("O")

# ---------------------------------------------------------------------------
# Task description registry
# ---------------------------------------------------------------------------
# Populated automatically in NodeTask.__post_init__ so create_task can
# look up the human-readable description by task_name without threading it
# through every call site.
_TASK_DESCRIPTIONS: dict[str, str] = {}


def get_task_description(task_name: str) -> str:
    """Return the registered description for *task_name*, or empty string."""
    return _TASK_DESCRIPTIONS.get(task_name, "")


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
        pg_cache_fn: Optional async function ``(input: I, ctx: NodeContext) -> O | None``
            called by ``run_task`` before invoking ``task_fn``.  When it returns a
            non-``None`` output, ``run_task`` short-circuits with a ``ToolCall``
            lifecycle record and returns the cached result — skipping both ``task_fn``
            and the Celery dispatch.  All tasks that previously implemented per-task
            cache checks should register their check here.
    """

    name: str
    description: str
    input_type: type[I]
    output_type: type[O]
    task_fn: Callable  # @task-decorated; awaited by BaseNode.run_task()
    handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
    pg_cache_fn: Callable[..., Awaitable[Any]] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Validate types and register the description in the global registry."""
        if not (isinstance(self.input_type, type) and issubclass(self.input_type, BaseModel)):
            raise TypeError(
                f"NodeTask '{self.name}': input_type must be a Pydantic BaseModel subclass, "
                f"got {self.input_type!r}"
            )
        if not (isinstance(self.output_type, type) and issubclass(self.output_type, BaseModel)):
            raise TypeError(
                f"NodeTask '{self.name}': output_type must be a Pydantic BaseModel subclass, "
                f"got {self.output_type!r}"
            )
        _TASK_DESCRIPTIONS[self.name] = self.description

    def get_input(self, payload: dict[str, Any]) -> I:
        """Parse and validate payload dict into the task's input Pydantic model.

        Args:
            payload: Raw dict to deserialise.

        Returns:
            Validated instance of ``input_type``.
        """
        return self.input_type.model_validate(payload)  # type: ignore[return-value]

    def get_output(self, data: dict[str, Any]) -> O:
        """Parse and validate data dict into the task's output Pydantic model.

        Args:
            data: Raw dict to deserialise.

        Returns:
            Validated instance of ``output_type``.
        """
        return self.output_type.model_validate(data)  # type: ignore[return-value]

    def as_tool(
        self,
        node: Any,
        ctx: Any,
        sink: dict[str, Any],
    ) -> Any:
        """Convert this NodeTask to a LangChain ``StructuredTool`` for agent use.

        The returned tool's coroutine delegates to ``node.run_task``, stores the
        ``TaskOutput`` in *sink* under ``self.name``, and returns the output
        content as a plain dict for the LLM.

        Args:
            node: The parent ``BaseNode`` instance that owns ``run_task()``.
            ctx:  Current ``NodeContext`` for the running node.
            sink: Mutable dict; the ``TaskOutput`` is stored here under
                  ``self.name`` when the tool is invoked.

        Returns:
            A ``StructuredTool`` whose async coroutine runs this task.
        """
        from langchain_core.tools import StructuredTool

        task_ref = self

        async def _run(**kwargs: Any) -> dict[str, Any]:
            inp = task_ref.input_type(**kwargs)
            result = await node.run_task(task_ref, ctx, inp)
            sink[task_ref.name] = result
            return result.content.model_dump()

        return StructuredTool.from_function(
            coroutine=_run,
            name=self.name,
            description=self.description,
            args_schema=self.input_type,
        )


__all__ = ["NodeTask", "get_task_description"]
