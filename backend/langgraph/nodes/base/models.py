"""Identity envelope models for the node/task hierarchy.

Hierarchy
---------
Thread (thread_id)
  └── Node  (NodeContext: thread_id + node_id + node_name)
        └── Task  (TaskContext extends NodeContext: + task_id + task_name)
              └── TaskInput[T] / TaskOutput[T]  (ctx + typed biz content)

Design intent
-------------
``NodeContext`` is the minimal identity carrier that every lifecycle call
(upsert_node, complete_node, create_task …) needs.  ``TaskContext`` extends
it so the full thread → node → task chain is available at the task layer
without needing to pass multiple IDs separately.

``TaskInput[T]`` separates identity (``ctx``) from biz payload (``content``).
This makes it trivial to log, trace, or route tasks purely by identity, and
keeps biz models clean of infrastructure fields.

Agent upgrade path
------------------
In agent mode, the LLM receives ``content`` as its tool input and produces
``TaskOutput[T].content`` as the tool output.  ``ctx`` is bound at
invocation time by ``BaseNode.run_task()`` — invisible to the LLM but always
present for tracing and persistence.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class NodeContext(BaseModel):
    """Thread → Node identity.  Passed to all lifecycle calls and run_task()."""

    thread_id: str
    node_id: str
    node_name: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskContext(NodeContext):
    """Extends NodeContext with per-invocation task identity."""

    task_id: str
    task_name: str


class TaskInput(BaseModel, Generic[T]):
    """Typed input envelope for a @task.

    Attributes:
        ctx: Full thread → node → task identity chain.
        content: Biz-specific input; type is fixed by the concrete subclass.
    """

    ctx: TaskContext
    content: T


class TaskOutput(BaseModel, Generic[T]):
    """Typed output envelope from a @task.  Mirrors TaskInput for traceability.

    Attributes:
        ctx: Same TaskContext that was passed in — carries origin identity.
        content: Biz-specific result; type is fixed by the concrete subclass.
    """

    ctx: TaskContext
    content: T


__all__ = ["NodeContext", "TaskContext", "TaskInput", "TaskOutput"]
