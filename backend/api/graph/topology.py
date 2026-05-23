"""Graph topology for the fin-analysis LangGraph.

This module exposes the full node/edge structure of the compiled graph,
including conditional routing branches, so the frontend can render a
complete topology diagram regardless of which branch actually executed.

``get_compiled_topology()`` extracts the live topology from the compiled
LangGraph instance (cached after the first call).  The legacy static
``GRAPH_TOPOLOGY`` constant is kept for the GET /api/v1/graph/topology
endpoint for backward compatibility.
"""

from __future__ import annotations

import logging
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator

from backend.langgraph.lifecycle.ids import strip_node_suffix

logger = logging.getLogger(__name__)

__all__ = [
    "TopologyNodeDef",
    "TopologyEdgeDef",
    "GraphTopologyResponse",
    "GRAPH_TOPOLOGY",
    "get_compiled_topology",
]

EdgeKind = Literal["sequential", "conditional"]


class TopologyNodeDef(BaseModel):
    """Single node in the static graph topology.

    Attributes:
        node_name: Registered LangGraph node name.
        node_type: ``"Workflow"`` or ``"Subgraph"``.
        conditional_group: When set, this node belongs to a conditional branch
            group.  All nodes sharing the same ``conditional_group`` are laid
            out as a vertical fan in the UI, with only the executed branch
            highlighted at runtime.
    """

    node_name: str
    node_type: str
    conditional_group: Optional[str] = None
    parallel_group: Optional[str] = None

    @field_validator("node_name", mode="before")
    @classmethod
    def _strip_node_name(cls, v: str) -> str:
        return strip_node_suffix(v)


class TopologyEdgeDef(BaseModel):
    """Directed edge between two nodes in the static graph topology.

    Attributes:
        from_node: Source node name.
        to_node: Target node name.
        kind: ``"sequential"`` for deterministic transitions; ``"conditional"``
            for branches selected at runtime by a routing function.
        condition_label: Human-readable description of the routing condition
            that causes this edge to be taken.  Only set on ``"conditional"``
            edges.  Shown in the UI as an edge tooltip on hover.
    """

    from_node: str
    to_node: str
    kind: EdgeKind
    condition_label: Optional[str] = None

    @field_validator("from_node", "to_node", mode="before")
    @classmethod
    def _strip_node_names(cls, v: str) -> str:
        return strip_node_suffix(v)


class GraphTopologyResponse(BaseModel):
    """Full static topology of the fin-analysis graph.

    Attributes:
        nodes: All possible nodes in declaration order (defines layout order).
        edges: All directed edges with kind annotations.
    """

    nodes: list[TopologyNodeDef] = Field(default_factory=list)
    edges: list[TopologyEdgeDef] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Static topology — mirrors build_graph() in backend.langgraph.graph
#
# Layout order of ``nodes`` determines left-to-right slot ordering in the UI.
# Nodes sharing a ``conditional_group`` are collapsed into a single vertical
# fan slot; exactly one of them will be highlighted by runtime data.
# ---------------------------------------------------------------------------

GRAPH_TOPOLOGY = GraphTopologyResponse(
    nodes=[
        TopologyNodeDef(node_name="query_node",       node_type="Workflow"),
        TopologyNodeDef(node_name="prepare_peers",    node_type="Agent",    parallel_group="analyze_parallel"),
        TopologyNodeDef(node_name="prepare_macro",    node_type="Workflow", parallel_group="analyze_parallel"),
        TopologyNodeDef(node_name="prepare_index",    node_type="Workflow", parallel_group="analyze_parallel"),
    ],
    edges=[
        TopologyEdgeDef(from_node="query_node",    to_node="prepare_peers",  kind="sequential"),
        TopologyEdgeDef(from_node="query_node",    to_node="prepare_macro",  kind="sequential"),
        TopologyEdgeDef(from_node="query_node",    to_node="prepare_index",  kind="sequential"),
    ],
)

# ---------------------------------------------------------------------------
# Runtime compiled-graph topology extraction
# ---------------------------------------------------------------------------

_compiled_topology_cache: Optional[GraphTopologyResponse] = None


def get_compiled_topology() -> GraphTopologyResponse:
    """Extract and cache the topology from the compiled LangGraph instance.

    Uses ``compiled_graph.get_graph()`` (xray=False) so subgraph nodes are
    opaque — no inner detail is revealed.  Conditional groups are inferred
    from edges: when multiple nodes share the same conditional-edge source,
    they are assigned a ``conditional_group`` named ``{source}_route``.

    Condition labels (human-readable routing descriptions) are overlaid from
    the static ``GRAPH_TOPOLOGY`` so they are not lost when using the compiled
    graph structure.

    Returns:
        :class:`GraphTopologyResponse` with nodes and edges from the live
        compiled graph.

    Raises:
        RuntimeError: If called before :func:`backend.langgraph.compiled.init_compiled_graph`.
    """
    global _compiled_topology_cache
    if _compiled_topology_cache is not None:
        return _compiled_topology_cache

    from backend.langgraph.compiled import get_compiled_graph

    graph = get_compiled_graph()
    drawable = graph.get_graph()  # xray=False keeps subgraphs opaque

    skip = {"__start__", "__end__"}

    # Detect subgraph nodes: their underlying runnable is itself a compiled
    # LangGraph (inherits from langgraph.pregel.Pregel).  We cannot use
    # hasattr(..., 'get_graph') because every LangChain Runnable exposes that
    # method — only a Pregel instance indicates a true compiled subgraph.
    subgraph_names: set[str] = set()
    try:
        from langgraph.pregel import Pregel as _Pregel
        for name, node_runner in graph.nodes.items():
            bound = getattr(node_runner, "bound", None) or getattr(node_runner, "runnable", None)
            if isinstance(bound, _Pregel):
                subgraph_names.add(name)
    except Exception:
        pass  # If detection fails, all nodes default to Workflow

    # Build conditional groups: nodes that all receive conditional edges from
    # the same source are grouped together (e.g. regional routing fan-out).
    cond_targets: dict[str, list[str]] = {}
    for edge in drawable.edges:
        if edge.conditional and edge.source not in skip and edge.target not in skip:
            cond_targets.setdefault(edge.source, []).append(edge.target)

    cond_group_map: dict[str, str] = {}
    for source, targets in cond_targets.items():
        if len(targets) > 1:
            group_name = f"{source}_route"
            for t in targets:
                cond_group_map[t] = group_name

    # Detect parallel groups: nodes that all receive sequential (non-conditional)
    # fan-out edges from the same source are assigned a parallel_group.
    par_targets: dict[str, list[str]] = {}
    for edge in drawable.edges:
        if not edge.conditional and edge.source not in skip and edge.target not in skip:
            par_targets.setdefault(edge.source, []).append(edge.target)

    par_group_map: dict[str, str] = {}
    for source, targets in par_targets.items():
        if len(targets) > 1:
            group_name = f"{source}_parallel"
            for t in targets:
                par_group_map[t] = group_name

    topology_nodes: list[TopologyNodeDef] = []
    for node_id in drawable.nodes:
        if node_id in skip:
            continue
        node_type = "Subgraph" if node_id in subgraph_names else "Workflow"
        topology_nodes.append(
            TopologyNodeDef(
                node_name=node_id,
                node_type=node_type,
                conditional_group=cond_group_map.get(node_id),
                parallel_group=par_group_map.get(node_id),
            )
        )

    # Build a static-label lookup: (from_node, to_node) → condition_label.
    # The compiled DrawableEdge has no human-readable labels, so we overlay
    # them from the manually maintained GRAPH_TOPOLOGY constant.
    static_labels: dict[tuple[str, str], str] = {
        (e.from_node, e.to_node): e.condition_label
        for e in GRAPH_TOPOLOGY.edges
        if e.condition_label
    }

    topology_edges: list[TopologyEdgeDef] = []
    for edge in drawable.edges:
        if edge.source in skip or edge.target in skip:
            continue
        kind: EdgeKind = "conditional" if edge.conditional else "sequential"
        topology_edges.append(
            TopologyEdgeDef(
                from_node=edge.source,
                to_node=edge.target,
                kind=kind,
                condition_label=static_labels.get(
                    (strip_node_suffix(edge.source), strip_node_suffix(edge.target))
                ),
            )
        )

    _compiled_topology_cache = GraphTopologyResponse(
        nodes=topology_nodes, edges=topology_edges
    )
    logger.debug("[topology] compiled topology cached: %d nodes, %d edges",
                 len(topology_nodes), len(topology_edges))
    return _compiled_topology_cache
