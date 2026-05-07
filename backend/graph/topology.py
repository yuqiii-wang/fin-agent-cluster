"""Static graph topology descriptor.

Provides the complete two-level topology of the outer LangGraph and all
inner subgraph structures so the frontend can:

* Pre-populate the outer view with pending nodes (including subgraph containers)
  before any SSE node events arrive.
* Know which inner nodes belong to which subgraph for zoom-in rendering.
* Render name-based edges in the outer view even for subgraph containers that
  never emit ``node_input`` / ``node_output`` SSE events.

The topology is entirely static and derived from :mod:`backend.graph.builder`
and :mod:`backend.graph.agents.node_types`.
"""

from __future__ import annotations

from pydantic import BaseModel

from backend.graph.agents.node_types import (
    NODE_TYPE_SUBGRAPH,
    NODE_TYPE_TYPICAL,
    get_subgraph_members,
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


class SubgraphTopology(BaseModel):
    """Inner topology for one subgraph container.

    Attributes:
        nodes: All inner nodes with their intra-subgraph parent relationships.
    """

    nodes: list[TopologyNode]


class GraphTopology(BaseModel):
    """Complete two-level graph topology.

    Attributes:
        outer_nodes: Top-level nodes including subgraph containers and outer
                     typical nodes, with static parent/child relationships.
        subgraphs:   Inner topologies keyed by subgraph container node name.
    """

    outer_nodes: list[TopologyNode]
    subgraphs: dict[str, SubgraphTopology]


def get_graph_topology() -> GraphTopology:
    """Return the complete static topology of the outer graph and all subgraphs.

    Outer edges mirror :func:`~backend.graph.builder.build_graph`::

        START → mock_perf_subgraph | mock_single_subgraph | fin_analyst_subgraph
        mock_single_subgraph → mock_analysis → mock_report → END
        mock_perf_subgraph   → END
        fin_analyst_subgraph → END

    Returns:
        :class:`GraphTopology` with outer and inner node descriptors.
    """
    outer_nodes: list[TopologyNode] = [
        TopologyNode(node_name="mock_perf_subgraph",   parent_node_names=[],                       node_type=NODE_TYPE_SUBGRAPH),
        TopologyNode(node_name="mock_single_subgraph", parent_node_names=[],                       node_type=NODE_TYPE_SUBGRAPH),
        TopologyNode(node_name="fin_analyst_subgraph", parent_node_names=[],                       node_type=NODE_TYPE_SUBGRAPH),
        TopologyNode(node_name="mock_analysis",         parent_node_names=["mock_single_subgraph"], node_type=NODE_TYPE_TYPICAL),
        TopologyNode(node_name="mock_report",           parent_node_names=["mock_analysis"],        node_type=NODE_TYPE_TYPICAL),
    ]

    # Inner topology for mock_perf_subgraph:
    #   perf-test path:   START → perf_runner → END
    mock_perf_inner = SubgraphTopology(nodes=[
        TopologyNode(node_name="perf_runner", parent_node_names=[], node_type=NODE_TYPE_TYPICAL),
    ])

    # Inner topology for mock_single_subgraph:
    #   prep path: START → query → [mock_news, mock_stats] → merge → END
    mock_single_inner = SubgraphTopology(nodes=[
        TopologyNode(node_name="query",      parent_node_names=[],                        node_type=NODE_TYPE_TYPICAL),
        TopologyNode(node_name="mock_news",  parent_node_names=["query"],                 node_type=NODE_TYPE_TYPICAL),
        TopologyNode(node_name="mock_stats", parent_node_names=["query"],                 node_type=NODE_TYPE_TYPICAL),
        TopologyNode(node_name="merge",      parent_node_names=["mock_news", "mock_stats"], node_type=NODE_TYPE_TYPICAL),
    ])

    # Inner topology for fin_analyst_subgraph:
    #   START → fin_analyst_runner → END
    fin_analyst_inner = SubgraphTopology(nodes=[
        TopologyNode(node_name="fin_analyst_runner", parent_node_names=[], node_type=NODE_TYPE_TYPICAL),
    ])

    return GraphTopology(
        outer_nodes=outer_nodes,
        subgraphs={
            "mock_perf_subgraph":   mock_perf_inner,
            "mock_single_subgraph": mock_single_inner,
            "fin_analyst_subgraph": fin_analyst_inner,
        },
    )


__all__ = [
    "TopologyNode",
    "SubgraphTopology",
    "GraphTopology",
    "get_graph_topology",
]
