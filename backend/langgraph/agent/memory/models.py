"""Pydantic model for task-output-derived agent memory.

An agent's "memory" is the set of finished task outputs produced by the tasks
it has already run within the same node execution.  Each :class:`TaskMemory`
entry is a live projection of one ``fin_agents.tasks`` row joined with the
output payload from its latest ``fin_agents.task_executions`` retry.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

# Statuses that count as a completed task whose output is usable as memory.
COMPLETED_STATUSES: tuple[str, ...] = ("completed",)
# Statuses that indicate a task failed and should be diagnosed on recovery.
FAILED_STATUSES: tuple[str, ...] = ("failed", "wrong")


class TaskMemory(BaseModel):
    """A single task-output memory entry for an agent node execution.

    Attributes:
        task_id:     UUID of the task row.
        node_id:     Owning agent node UUID.
        node_name:   Workflow node name.
        task_name:   Registered NodeTask name.
        description: Human-readable task description (from the tasks row).
        status:      Task status (e.g. ``"completed"``, ``"failed"``).
        output:      Latest-retry output payload, or ``None`` when not loaded.
        updated_at:  Last update timestamp of the task row.
    """

    task_id: str
    node_id: str
    node_name: str
    task_name: str
    description: str
    status: str
    output: dict[str, Any] | None = None
    updated_at: datetime | None = None

    model_config = {"frozen": True}


__all__ = ["TaskMemory", "COMPLETED_STATUSES", "FAILED_STATUSES"]
