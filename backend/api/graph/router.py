"""backend.api.graph — graph topology inspection endpoints.

Routes
------
    GET  /api/v1/graph/topology    — full static node/edge topology (no auth required)
    GET  /api/v1/graph/node-metas  — per-node UI metadata for the preferences panel
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.api.graph.topology import GraphTopologyResponse, GRAPH_TOPOLOGY
from backend.api.graph.node_metas import NodeMetaResponse, get_node_metas

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


@router.get("/node-metas", response_model=list[NodeMetaResponse])
async def get_graph_node_metas() -> list[NodeMetaResponse]:
    """Return UI metadata for all configurable graph nodes.

    The list starts with the ``__global__`` virtual entry (graph-wide defaults)
    followed by one entry per production node that declares ``config_fields``.
    The frontend uses this to render the per-node agent preferences panel
    without any hardcoded metadata on the client side.
    """
    return get_node_metas()
