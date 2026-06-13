"""Identity envelope models for the node/task hierarchy.

Hierarchy
---------
Thread (thread_id)
  └── Node  (NodeContext: thread_id + node_id + node_name + version)
        └── Task  (TaskContext extends NodeContext: + task_id + task_name)
              └── TaskInput[T] / TaskOutput[T]  (ctx + typed biz content)

Design intent
-------------
``NodeContext`` is the minimal identity carrier that every lifecycle call
(upsert_node, complete_node, create_task ...) needs.  ``TaskContext`` extends
it so the full thread -> node -> task chain is available at the task layer
without needing to pass multiple IDs separately.

``TaskInput[T]`` separates identity (``ctx``) from biz payload (``content``).
This makes it trivial to log, trace, or route tasks purely by identity, and
keeps biz models clean of infrastructure fields.

Agent upgrade path
------------------
In agent mode, the LLM receives ``content`` as its tool input and produces
``TaskOutput[T].content`` as the tool output.  ``ctx`` is bound at
invocation time by ``BaseNode.run_task()`` -- invisible to the LLM but always
present for tracing and persistence.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class BaseTaskInput(BaseModel):
    """Base input model for all task inputs.

    Provides infrastructure-level control fields that ``run_task`` reads before
    dispatching to the ``@task`` function.  Business-specific input models should
    inherit from this class instead of ``BaseModel`` directly.

    Attributes:
        from_maybe_cache: When ``True`` (default) ``run_task`` checks existing
                          completed task rows and ``pg_cache_fn`` before
                          delegating to Celery.  When ``False`` all DB/PG cache
                          reads are bypassed and a fresh execution is forced.
                          Retries driven by ``llm_orchestration_on_failure``
                          propose new inputs, which change the task input hash
                          and naturally bypass the cache without toggling this.
    """

    from_maybe_cache: bool = Field(
        default=True,
        description=(
            "When False, bypass all DB/PG cache reads and force fresh execution."
        ),
    )


class NodeContext(BaseModel):
    """Thread -> Node identity.  Passed to all lifecycle calls and run_task()."""

    # Allow mutation so BaseNode.__call__ can accumulate task_ids after tasks start.
    model_config = ConfigDict(frozen=False)

    thread_id: str
    node_id: str
    node_name: str
    # Fork generation counter that was active when this node was dispatched.
    # Used to compute the UUID5 node_id and to set version in the DB row.
    version: int = 1
    # Predecessor node IDs in the current branch (for topology recording).
    prev_node_ids: list[str] = Field(default_factory=list)
    # Task IDs accumulated during this node's execution.  Mutable so that
    # run_task() can append before delegating to the @task function.
    task_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskContext(NodeContext):
    """Extends NodeContext with per-invocation task identity."""

    task_id: str
    task_name: str


class TaskInput(BaseModel, Generic[T]):
    """Typed input envelope for a @task.

    Attributes:
        ctx:    Full thread -> node -> task identity chain.
        content: Biz-specific input; type is fixed by the concrete subclass.
        memory: In-flight agent memory accumulated by the enclosing agent node
                across its execution loop.  Empty list on the first iteration.
                Entries are opaque dicts whose schema is defined by the node
                that manages the memory (e.g. ``prepare_peers`` writes
                ``{"symbol", "corr", "status"}`` entries after each
                ``analyze_peer_corr`` call).  Read-only inside task functions.
    """

    ctx: TaskContext
    content: T
    memory: list[dict] = Field(default_factory=list)


class TaskOutput(BaseModel, Generic[T]):
    """Typed output envelope from a @task.  Mirrors TaskInput for traceability.

    Attributes:
        ctx:      Same TaskContext that was passed in -- carries origin identity.
        content:  Biz-specific result; type is fixed by the concrete subclass.
        thinking: Chain-of-thought text captured from streaming tasks.  Set by
                  streaming ``@task`` functions so the agent loop can store it
                  in memory alongside the structured answer.
    """

    ctx: TaskContext
    content: T
    thinking: str | None = None


class TaskRecord(BaseModel):
    """Lightweight record to store in checkpoints instead of full TaskOutput.

    Contains only identifiers to recover the full task data from Postgres.
    """

    thread_id: str
    node_id: str
    task_id: str


__all__ = ["NodeContext", "TaskContext", "TaskInput", "TaskOutput", "TaskRecord", "BaseTaskInput"]
