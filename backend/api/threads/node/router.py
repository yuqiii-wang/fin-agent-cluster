"""backend.api.threads.node -- node-level API endpoints.

Routes (all mounted on the parent ``/threads`` router):

    GET  /api/v1/threads/{thread_id}/nodes                          -- list all node executions
    POST /api/v1/threads/{thread_id}/nodes/{node_id}/cancel         -- cancel a node
    POST /api/v1/threads/{thread_id}/nodes/{node_id}/re-explore     -- fork at pre-node checkpoint
    POST /api/v1/threads/{thread_id}/nodes/{node_id}/invalidate-cache -- zero out task cache TTLs
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path

from backend.api.errors import API_NODE_CACHE_INVALIDATE_DB_ERROR
from backend.users.queries import cancel_node, get_node_executions, re_explore_node
from backend.users.schemas import NodeExecutionInfo, QueryResponse, ReExploreRequest
from backend.api.threads.node.agent.router import router as agent_router
from backend.langgraph.lifecycle.threads.nodes.tasks.ops import invalidate_node_task_caches

logger = logging.getLogger(__name__)

router = APIRouter()
router.include_router(agent_router)

TThreadId = Annotated[str, Path(description="LangGraph thread UUID")]
TNodeId = Annotated[str, Path(description="Node execution UUID")]


# ---------------------------------------------------------------------------
# Node-level
# ---------------------------------------------------------------------------


@router.get("/{thread_id}/nodes", response_model=list[NodeExecutionInfo], tags=["node"])
async def list_nodes_route(thread_id: TThreadId) -> list[NodeExecutionInfo]:
    """Return all node-level executions for a thread."""
    return await get_node_executions(thread_id)


@router.post("/{thread_id}/nodes/{node_id}/cancel", tags=["node"])
async def cancel_node_route(thread_id: TThreadId, node_id: TNodeId) -> dict:
    """Cancel a specific node execution and all tasks running under it."""
    return await cancel_node(thread_id, node_id)


@router.post(
    "/{thread_id}/nodes/{node_id}/re-explore",
    response_model=QueryResponse,
    tags=["node"],
)
async def re_explore_node_route(
    thread_id: TThreadId,
    node_id: TNodeId,
    body: ReExploreRequest,
) -> QueryResponse:
    """Fork the graph at the checkpoint just before node_id ran and re-execute from there.

    Optionally accepts ``input_override`` to inject different GraphState values
    into the forked checkpoint before dispatching, allowing the user to change
    the inputs the re-explored node will receive.
    """
    return await re_explore_node(thread_id, node_id, input_override=body.input_override)


@router.post("/{thread_id}/nodes/{node_id}/invalidate-cache", tags=["node"])
async def invalidate_node_cache_route(thread_id: TThreadId, node_id: TNodeId) -> dict:
    """Zero out cache_ttl_seconds for all completed tasks under node_id.

    After this call the tasks will be re-executed on the next run instead of
    being served from the task cache.
    """
    try:
        invalidated = await invalidate_node_task_caches(thread_id, node_id)
    except Exception as exc:
        logger.error(
            "[%s] invalidate_node_cache DB error thread_id=%s node_id=%s: %s",
            API_NODE_CACHE_INVALIDATE_DB_ERROR, thread_id, node_id, exc,
        )
        raise HTTPException(status_code=500, detail=API_NODE_CACHE_INVALIDATE_DB_ERROR) from exc
    return {"invalidated": invalidated}

