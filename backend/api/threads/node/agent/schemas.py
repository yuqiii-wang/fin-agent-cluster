"""Request / response schemas for the agent capabilities API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from backend.langgraph.agent.memory.models import MemoryEntry
from backend.langgraph.agent.skills.models import Skill


class AddSkillRequest(BaseModel):
    """Request body for adding a new user-defined skill to an agent node."""

    summary: str
    """One-line human-readable label for the skill."""

    instructions: str
    """Full instruction text; appended to the agent's system prompt."""


class CompactMemoryRequest(BaseModel):
    """Request body for compacting a set of memory entries into a summary."""

    memory_ids: list[str]
    """UUIDs of the active memory entries to compact (minimum 2)."""

    summary: str
    """Human-readable text that replaces the compacted entries."""


class SkillResponse(BaseModel):
    """Response after creating a new skill."""

    skill_id: str
    status: str


class MemoryOperationResponse(BaseModel):
    """Response after a memory forget or compact operation."""

    memory_id: str
    """ID of the affected (forgotten) or newly created (compacted_summary) entry."""

    status: str


class AgentCapabilitiesResponse(BaseModel):
    """Full capability snapshot returned by GET .../agent/capabilities."""

    tools: list[dict[str, Any]]
    """Fixed NodeTask tools available to the agent."""

    skills: list[Skill]
    """User-defined active skills attached to this node execution."""

    memory: list[MemoryEntry]
    """Chronological active memory entries from this node execution."""


__all__ = [
    "AddSkillRequest",
    "AgentCapabilitiesResponse",
    "CompactMemoryRequest",
    "MemoryOperationResponse",
    "SkillResponse",
]
