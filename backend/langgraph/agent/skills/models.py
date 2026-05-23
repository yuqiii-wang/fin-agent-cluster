"""Pydantic models for agent skills."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

SkillStatus = Literal["active", "forgotten"]


class Skill(BaseModel):
    """A user-defined skill (instruction) attached to an agent node execution."""

    skill_id: str
    thread_id: str
    node_id: str
    summary: str
    instructions: str
    status: SkillStatus
    created_at: datetime

    model_config = {"frozen": True}


__all__ = ["Skill", "SkillStatus"]
