"""Static graph topology descriptor.

Provides the query-filtered topology of the outer LangGraph and the relevant
inner graph so the frontend can:

* Pre-populate the outer view with pending nodes (including graph containers)
  before any SSE node events arrive.
* Know which inner nodes belong to which graph for zoom-in rendering.
* Render name-based edges in the outer view even for graph containers that
  never emit ``node_input`` / ``node_output`` SSE events.

The topology is query-driven: only the graph branch that ``_route_query``
will execute is included, so the frontend sees exactly one routed graph.
"""

from __future__ import annotations

from pydantic import BaseModel

from backend.graph.agents.mock_perf import PERF_TEST_TRIGGER
from backend.graph.agents.mock_single import MOCK_SINGLE_TRIGGER
from backend.graph.agents.node_types import (
    NODE_TYPE_SUBGRAPH,
    NODE_TYPE_TYPICAL,
)


class TopologyNode(BaseModel):
    """A single node descriptor in a graph topology.

    Attributes:
        node_name:          LangGraph node name.
        parent_node_names:  Static parent names within the same graph level.
        node_type:          ``'Typical'``, ``'Subgraph'``, or ``'Reference'``.
    """

    node_name: str
    parent_node_names: list[str]
    node_type: str


class InnerSubgraphTopology(BaseModel):
    """Inner topology for one graph container.

    Attributes:
        nodes: All inner nodes with their intra-graph parent relationships.
    """

    nodes: list[TopologyNode]


class GraphTopology(BaseModel):
    """Query-filtered two-level graph topology.

    Attributes:
        outer_nodes: Top-level nodes for the routed branch only.
        subgraphs:   Inner topologies keyed by graph container node name.
    """

    outer_nodes: list[TopologyNode]
    subgraphs: dict[str, InnerSubgraphTopology]


def get_graph_topology(query: str) -> GraphTopology:
    """Return the query-filtered topology for the routed graph branch.

    Only the branch that ``_route_query`` will execute is returned, so the
    frontend pre-populates exactly one graph container node.

    Routing mirrors :func:`~backend.graph.builder._route_query`:

    * PERF_TEST_TRIGGER  → ``mock_perf_graph``
    * MOCK_SINGLE_TRIGGER → ``mock_single_graph`` + ``mock_analysis`` + ``mock_report``
    * all others          → ``fin_analyst_graph``

    Args:
        query: Raw query text (case-insensitive prefix match used for routing).

    Returns:
        :class:`GraphTopology` with outer and inner node descriptors for the
        routed branch only.
    """
    normalised = query.strip().upper()

    if normalised.startswith(PERF_TEST_TRIGGER):
        outer_nodes: list[TopologyNode] = [
            TopologyNode(node_name="mock_perf_graph", parent_node_names=[], node_type=NODE_TYPE_SUBGRAPH),
        ]
        subgraphs: dict[str, InnerSubgraphTopology] = {
            "mock_perf_graph": InnerSubgraphTopology(nodes=[
                TopologyNode(node_name="perf_runner", parent_node_names=[], node_type=NODE_TYPE_TYPICAL),
            ]),
        }

    elif normalised.startswith(MOCK_SINGLE_TRIGGER):
        outer_nodes = [
            TopologyNode(node_name="mock_single_graph", parent_node_names=[],                      node_type=NODE_TYPE_SUBGRAPH),
            TopologyNode(node_name="mock_analysis",      parent_node_names=["mock_single_graph"],   node_type=NODE_TYPE_TYPICAL),
            TopologyNode(node_name="mock_report",        parent_node_names=["mock_analysis"],       node_type=NODE_TYPE_TYPICAL),
        ]
        subgraphs = {
            "mock_single_graph": InnerSubgraphTopology(nodes=[
                TopologyNode(node_name="query",      parent_node_names=[],                          node_type=NODE_TYPE_TYPICAL),
                TopologyNode(node_name="mock_news",  parent_node_names=["query"],                   node_type=NODE_TYPE_TYPICAL),
                TopologyNode(node_name="mock_stats", parent_node_names=["query"],                   node_type=NODE_TYPE_TYPICAL),
                TopologyNode(node_name="merge",      parent_node_names=["mock_news", "mock_stats"], node_type=NODE_TYPE_TYPICAL),
            ]),
        }

    else:
        outer_nodes = [
            TopologyNode(node_name="fin_analyst_graph", parent_node_names=[], node_type=NODE_TYPE_SUBGRAPH),
        ]
        subgraphs = {
            "fin_analyst_graph": InnerSubgraphTopology(nodes=[
                TopologyNode(node_name="fin_analyst_runner", parent_node_names=[], node_type=NODE_TYPE_TYPICAL),
            ]),
        }

    return GraphTopology(outer_nodes=outer_nodes, subgraphs=subgraphs)


__all__ = [
    "TopologyNode",
    "InnerSubgraphTopology",
    "GraphTopology",
    "get_graph_topology",
]

