"""Pydantic models for agent memory entries.

Two flavours of memory entry exist per node:

* **Task-backed memory** — ``task_id`` is set; ``content`` may be ``None``.
  The effective payload is the latest ``fin_agents.task_executions.output``
  for the referenced task.  This is how the agent remembers outputs from
  tasks it already ran.
* **Direct memory** — ``task_id`` is ``None``; ``content`` is a non-empty
  JSONB payload written directly via :func:`write_memory`.  This is the
  general-purpose scratchpad for arbitrary node-scoped state.

All entries are scoped to a single ``node_id`` (i.e. a single run of a
single node).  Each entry is addressable both by ``memory_id`` (UUID) and
``name`` (unique human-readable label within the node).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class MemoryItem(BaseModel):
    """A single memory entry for a node execution.

    Attributes:
        memory_id:   UUID primary key of the memory row.
        thread_id:   Owning thread (matches fin_agents.user_queries.thread_id).
        node_id:     Owning node (matches fin_agents.nodes.node_id).
        task_id:     Optional FK to fin_agents.tasks; when set, content may be
                     None (the content is then the referenced task's output).
        name:        Stable logical name; unique within (node_id).  Used for
                     name-based lookups.
        description: Human-readable description shown to the agent / UI when
                     listing memory contents.
        content:     JSONB payload.  None for task-backed entries (task_id is
                     set); must be a non-empty JSON value for direct entries.
        effective_content: The resolved content actually used at read-time —
                     either the stored ``content``, or the referenced task's
                     output (when task_id is set and content is None).
        task_name:   Name of the referenced task (fin_agents.tasks.task_name),
                     or None when task_id is None.
        task_status: Status of the referenced task, or None when task_id is None.
        created_at:  Creation timestamp of the memory row.
        updated_at:  Last update timestamp of the memory row.
    """

    memory_id: str
    thread_id: str
    node_id: str
    task_id: str | None = None
    name: str
    description: str = ""
    content: dict[str, Any] | None = None
    effective_content: dict[str, Any] | None = None
    task_name: str | None = None
    task_status: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"frozen": True}


class MemoryCheckItem(BaseModel):
    """Lightweight descriptor for a memory entry (without payload).

    Used by :func:`check_memory` and for UI listings where the actual content
    is not yet needed (e.g. the agent choosing which memory entry to pull).
    """

    memory_id: str
    name: str
    description: str
    task_id: str | None = None
    created_at: datetime | None = None

    model_config = {"frozen": True}


__all__ = ["MemoryItem", "MemoryCheckItem"]
