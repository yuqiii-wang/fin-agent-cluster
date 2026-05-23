"""backend.api.threads.node — node-level API endpoints.

Routes (all mounted on the parent ``/threads`` router):

    GET  /api/v1/threads/{thread_id}/nodes                          — list all node executions
    POST /api/v1/threads/{thread_id}/nodes/{node_id}/cancel         — cancel a node
    POST /api/v1/threads/{thread_id}/nodes/{node_id}/re-explore     — fork at pre-node checkpoint
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path

from backend.users.queries import cancel_node, get_node_executions, re_explore_node
from backend.users.schemas import NodeExecutionInfo, QueryResponse, ReExploreRequest

router = APIRouter()

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


from backend.api.threads.node.agent.router import router as agent_router  # noqa: E402
router.include_router(agent_router)

