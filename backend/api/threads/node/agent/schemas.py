"""Request / response schemas for the agent capabilities API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from backend.langgraph.agent.memory import MemoryItem
from backend.langgraph.agent.skills.models import Skill


class AddSkillRequest(BaseModel):
    """Request body for adding a new user-defined skill to an agent node."""

    summary: str
    """One-line human-readable label for the skill."""

    instructions: str
    """Full instruction text; appended to the agent's system prompt."""


class SkillResponse(BaseModel):
    """Response after creating or forgetting a skill."""

    skill_id: str
    status: str


class AgentCapabilitiesResponse(BaseModel):
    """Full capability snapshot returned by GET .../agent/capabilities."""

    tools: list[dict[str, Any]]
    """Fixed NodeTask tools available to the agent."""

    skills: list[Skill]
    """User-defined active skills attached to this node execution."""

    memory: list[MemoryItem]
    """Memory entries from ``fin_agents.agent_memory`` for this node execution."""


__all__ = [
    "AddSkillRequest",
    "AgentCapabilitiesResponse",
    "SkillResponse",
]
