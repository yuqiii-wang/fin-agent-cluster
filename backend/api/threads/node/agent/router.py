"""backend.api.threads.node.agent — agent capabilities API router.

Routes (all mounted on the parent ``/threads`` router):

    GET  /api/v1/threads/{thread_id}/nodes/{node_id}/agent/capabilities
         — return tools, skills, and memory for an agent node.

    POST /api/v1/threads/{thread_id}/nodes/{node_id}/agent/skills
         — add a user-defined skill; if node is running, sets pause+auto_resume.

    POST /api/v1/threads/{thread_id}/nodes/{node_id}/agent/memory/{memory_id}/forget
         — mark a memory entry as forgotten; if node is running, sets pause+auto_resume.

    POST /api/v1/threads/{thread_id}/nodes/{node_id}/agent/memory/compact
         — compact selected entries into a summary; if node is running, sets pause+auto_resume.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path

from backend.api.threads.node.agent.errors import (
    AGENT_API_COMPACT_TOO_FEW,
    AGENT_API_MEMORY_NOT_FOUND,
    AGENT_API_NODE_NOT_FOUND,
    AGENT_API_SKILL_NOT_FOUND,
    AGENT_API_STEP_STATE_NOT_FOUND,
)
from backend.api.threads.node.agent.schemas import (
    AddSkillRequest,
    AgentCapabilitiesResponse,
    AgentStepStatesResponse,
    CompactMemoryRequest,
    MemoryOperationResponse,
    SkillResponse,
)
from backend.db.postgres import raw_conn
from backend.langgraph.agent.capabilities import AgentCapabilities, get_agent_capabilities
from backend.langgraph.agent.memory.ops import (
    compact_memory_entries,
    forget_memory_entry,
)
from backend.langgraph.agent.pause import set_agent_pause_flag
from backend.langgraph.agent.skills.ops import add_skill, forget_skill
from backend.langgraph.agent.step_state.ops import get_step_states

router = APIRouter()

TThreadId = Annotated[str, Path(description="LangGraph thread UUID")]
TNodeId = Annotated[str, Path(description="Node execution UUID")]
TMemoryId = Annotated[str, Path(description="Memory entry UUID")]


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
    """Return the current tools, skills, and memory for an agent node execution.

    For non-running (terminal) nodes all memory entries including forgotten and
    compacted originals are returned so the UI can display the full history in
    read-only/immutable mode.
    """
    is_running = await _is_node_running(thread_id, node_id)

    caps: AgentCapabilities = await get_agent_capabilities(node_id, include_all_memory=not is_running)
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


@router.post(
    "/{thread_id}/nodes/{node_id}/agent/memory/{memory_id}/forget",
    response_model=MemoryOperationResponse,
    tags=["agent"],
)
async def forget_memory_route(
    thread_id: TThreadId,
    node_id: TNodeId,
    memory_id: TMemoryId,
) -> MemoryOperationResponse:
    """Mark a memory entry as forgotten so it is excluded from the agent's context.

    If the node is currently running, sets pause+auto_resume so the agent
    restarts without the forgotten entry in its context window.
    """
    is_running = await _is_node_running(thread_id, node_id)

    updated = await forget_memory_entry(node_id, memory_id)
    if not updated:
        raise HTTPException(
            status_code=404,
            detail=f"[{AGENT_API_MEMORY_NOT_FOUND}] Memory entry {memory_id} not found or already non-active on node {node_id}",
        )

    if is_running:
        await set_agent_pause_flag(node_id, auto_resume=True)

    return MemoryOperationResponse(memory_id=memory_id, status="forgotten")


@router.post(
    "/{thread_id}/nodes/{node_id}/agent/memory/compact",
    response_model=MemoryOperationResponse,
    tags=["agent"],
)
async def compact_memory_route(
    thread_id: TThreadId,
    node_id: TNodeId,
    body: CompactMemoryRequest,
) -> MemoryOperationResponse:
    """Compact selected memory entries into a single summary entry.

    Requires at least 2 active entries.  If the node is currently running,
    sets pause+auto_resume so the agent restarts with the compacted context.
    """
    if len(body.memory_ids) < 2:
        raise HTTPException(
            status_code=422,
            detail=f"[{AGENT_API_COMPACT_TOO_FEW}] compact_memory requires at least 2 memory_ids",
        )

    is_running = await _is_node_running(thread_id, node_id)

    new_memory_id = await compact_memory_entries(thread_id, node_id, body.memory_ids, body.summary)
    if new_memory_id is None:
        raise HTTPException(
            status_code=422,
            detail=f"[{AGENT_API_COMPACT_TOO_FEW}] Fewer than 2 active entries found for the provided memory_ids",
        )

    if is_running:
        await set_agent_pause_flag(node_id, auto_resume=True)

    return MemoryOperationResponse(memory_id=new_memory_id, status="compacted")


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


@router.get(
    "/{thread_id}/nodes/{node_id}/agent/step-states",
    response_model=AgentStepStatesResponse,
    tags=["agent"],
)
async def get_step_states_route(
    thread_id: TThreadId,
    node_id: TNodeId,
) -> AgentStepStatesResponse:
    """Return per-iteration global_state and step_state snapshots for an agent node.

    Args:
        thread_id: LangGraph thread UUID (used to verify node ownership).
        node_id:   Agent node UUID.

    Returns:
        :class:`AgentStepStatesResponse` with all iterations ordered ascending.

    Raises:
        HTTPException 404: Node not found in the given thread.
    """
    await _is_node_running(thread_id, node_id)  # validates ownership; raises 404 if missing
    entries = await get_step_states(node_id)
    return AgentStepStatesResponse(iterations=entries)
