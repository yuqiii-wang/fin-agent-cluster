"""_shared.models — base Pydantic models inherited by every node and task.

All node and task I/O models must inherit from the appropriate base class so
that the minimum required fields are always present on every payload written to
``node_executions.input`` / ``node_executions.output`` and
``fin_agents.tasks.input`` / ``fin_agents.tasks.output``.

Hierarchy
---------
Node models:
    NodeBaseInput  ← every node input model
    NodeBaseOutput ← every node output model

Task models:
    TaskBaseInput  ← every task input model
    TaskBaseOutput ← every task output model
"""

from backend.graph.agents._shared.models.base import (
    NodeBaseInput,
    NodeBaseOutput,
    TaskBaseInput,
    TaskBaseOutput,
)

__all__ = [
    "NodeBaseInput",
    "NodeBaseOutput",
    "TaskBaseInput",
    "TaskBaseOutput",
]
