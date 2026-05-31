"""Agent capability snapshot for the API layer.

An agent node's capabilities are:

- ``tools``  — the fixed ``NodeTask`` tools registered on the node class.
- ``skills`` — user-defined active skill instructions attached to the node.
- ``memory`` — the live set of finished task outputs produced by the node,
  projected from ``fin_agents.tasks`` (see :mod:`backend.langgraph.agent.memory`).

This module exposes a single entry point, :func:`get_agent_capabilities`,
consumed by ``GET /api/v1/threads/{thread_id}/nodes/{node_id}/agent/capabilities``.
"""

from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel

from backend.langgraph.agent.memory.models import TaskMemory
from backend.langgraph.agent.memory.ops import get_task_memory
from backend.langgraph.agent.skills.models import Skill
from backend.langgraph.agent.skills.ops import get_skills
from backend.langgraph.agent.tools.models import ToolInfo
from backend.langgraph.agent.tools.ops import get_tools_for_node

logger = logging.getLogger(__name__)


class AgentCapabilities(BaseModel):
    """Full capability snapshot for an agent node execution (API view).

    Attributes:
        tools:  Fixed NodeTask tools registered on the node class.
        skills: User-defined active skill instructions for this node.
        memory: Completed task outputs produced by this node execution.
    """

    tools: list[ToolInfo]
    skills: list[Skill]
    memory: list[TaskMemory]


async def get_agent_capabilities(node_id: str) -> AgentCapabilities:
    """Return the full capability snapshot for *node_id*.

    Memory is built live from the node's completed task outputs — no dedicated
    memory table is consulted.

    Args:
        node_id: Agent node UUID.

    Returns:
        :class:`AgentCapabilities` with tools, active skills, and task memory.
    """
    tools_task = asyncio.create_task(get_tools_for_node(node_id))
    skills_task = asyncio.create_task(get_skills(node_id, active_only=True))
    memory_task = asyncio.create_task(get_task_memory(node_id, with_output=True))

    tools, skills, memory = await asyncio.gather(tools_task, skills_task, memory_task)

    return AgentCapabilities(tools=tools, skills=skills, memory=memory)


__all__ = ["AgentCapabilities", "get_agent_capabilities"]
