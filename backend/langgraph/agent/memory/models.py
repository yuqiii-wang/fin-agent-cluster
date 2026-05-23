"""Pydantic models for agent memory entries."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

MemoryEntryType = Literal[
    "task_result",
    "tool_call",
    "skill_applied",
    "reasoning",
    "compacted_summary",
]

MemoryStatus = Literal["active", "forgotten", "compacted"]


class MemoryEntry(BaseModel):
    """A single chronological memory entry for an agent node execution."""

    memory_id: str
    thread_id: str
    node_id: str
    entry_type: MemoryEntryType
    content: dict[str, Any]
    seq_num: int
    status: MemoryStatus
    compacted_into: str | None = None
    created_at: datetime

    model_config = {"frozen": True}


__all__ = ["MemoryEntry", "MemoryEntryType", "MemoryStatus"]
