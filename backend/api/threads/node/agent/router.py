"""backend.api.threads.node.agent -- agent capabilities API router.

Routes (all mounted on the parent ``/threads`` router):

    GET  /api/v1/threads/{thread_id}/nodes/{node_id}/agent/capabilities
         -- return tools, skills, and task-output memory for an agent node.

    POST /api/v1/threads/{thread_id}/nodes/{node_id}/agent/skills
         -- add a user-defined skill; if node is running, sets pause+auto_resume.

    POST /api/v1/threads/{thread_id}/nodes/{node_id}/agent/skills/{skill_id}/forget
         -- mark a skill as forgotten; if node is running, sets pause+auto_resume.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path

from backend.api.threads.node.agent.errors import (
    AGENT_API_NODE_NOT_FOUND,
    AGENT_API_SKILL_NOT_FOUND,
)
from backend.api.threads.node.agent.schemas import (
    AddSkillRequest,
    AgentCapabilitiesResponse,
    SkillResponse,
)
from backend.db.postgres import raw_conn
from backend.langgraph.agent.capabilities import AgentCapabilities, get_agent_capabilities
from backend.langgraph.agent.pause import set_agent_pause_flag
from backend.langgraph.agent.skills.ops import add_skill, forget_skill

router = APIRouter()

TThreadId = Annotated[str, Path(description="LangGraph thread UUID")]
TNodeId = Annotated[str, Path(description="Node execution UUID")]


async def _is_node_running(thread_id: str, node_id: str) -> bool:
    """Return ``True`` when *node_id* currently has status ``'running'``.

    Args:
        thread_id: LangGraph thread UUID (safety scoping).
        node_id:   Agent node UUID.
    """
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            "SELECT status FROM fin_agents.nodes WHERE node_id = %s AND thread_id = %s",
            (node_id, thread_id),
        )
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"[{AGENT_API_NODE_NOT_FOUND}] Node {node_id} not found in thread {thread_id}",
        )
    return row["status"] == "running"


@router.get(
    "/{thread_id}/nodes/{node_id}/agent/capabilities",
    response_model=AgentCapabilitiesResponse,
    tags=["agent"],
)
async def get_capabilities_route(
    thread_id: TThreadId,
    node_id: TNodeId,
) -> AgentCapabilitiesResponse:
    """Return the current tools, skills, and task-output memory for an agent node."""
    await _is_node_running(thread_id, node_id)  # validates ownership; raises 404 if missing

    caps: AgentCapabilities = await get_agent_capabilities(node_id)
    return AgentCapabilitiesResponse(
        tools=[t.model_dump() for t in caps.tools],
        skills=list(caps.skills),
        memory=list(caps.memory),
    )


@router.post(
    "/{thread_id}/nodes/{node_id}/agent/skills",
    response_model=SkillResponse,
    tags=["agent"],
)
async def add_skill_route(
    thread_id: TThreadId,
    node_id: TNodeId,
    body: AddSkillRequest,
) -> SkillResponse:
    """Add a user-defined skill to the running agent node.

    If the node is currently running, sets the Redis pause+auto_resume flags so
    the agent loop restarts with the new skill applied to its system prompt.
    Returns 200 immediately after persisting the skill.
    """
    is_running = await _is_node_running(thread_id, node_id)

    skill = await add_skill(thread_id, node_id, body.summary, body.instructions)

    if is_running:
        await set_agent_pause_flag(node_id, auto_resume=True)

    return SkillResponse(skill_id=skill.skill_id, status=skill.status)


TSkillId = Annotated[str, Path(description="Skill UUID")]


@router.post(
    "/{thread_id}/nodes/{node_id}/agent/skills/{skill_id}/forget",
    response_model=SkillResponse,
    tags=["agent"],
)
async def forget_skill_route(
    thread_id: TThreadId,
    node_id: TNodeId,
    skill_id: TSkillId,
) -> SkillResponse:
    """Mark a skill as forgotten so it is no longer applied to the agent's context.

    If the node is currently running, sets pause+auto_resume so the agent
    restarts without the forgotten skill.
    """
    is_running = await _is_node_running(thread_id, node_id)

    updated = await forget_skill(node_id, skill_id)
    if not updated:
        raise HTTPException(
            status_code=404,
            detail=f"[{AGENT_API_SKILL_NOT_FOUND}] Skill {skill_id} not found or already forgotten on node {node_id}",
        )

    if is_running:
        await set_agent_pause_flag(node_id, auto_resume=True)

    return SkillResponse(skill_id=skill_id, status="forgotten")
