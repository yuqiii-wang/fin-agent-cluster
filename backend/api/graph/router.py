"""backend.api.graph — graph topology inspection endpoints.

Routes
------
    GET  /api/v1/graph/topology   — full static node/edge topology (no auth required)
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.api.graph.topology import GraphTopologyResponse, GRAPH_TOPOLOGY

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/topology", response_model=GraphTopologyResponse)
async def get_graph_topology() -> GraphTopologyResponse:
    """Return the complete static topology of the fin-analysis LangGraph.

    The response includes every possible node and directed edge, including
    conditional branches that may not execute for a given query.  The frontend
    uses this to render a full topology diagram and overlays runtime status
    on the executed branch.
    """
    return GRAPH_TOPOLOGY
