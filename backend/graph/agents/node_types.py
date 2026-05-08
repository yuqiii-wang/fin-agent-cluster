"""Node type registry — maps node_name to its classification.

Node types mirror the ``fin_agents.nodes.type`` CHECK constraint:

* ``'Typical'``   — a regular LangGraph node that performs computation.
* ``'Subgraph'``  — a LangGraph node whose action is a compiled
                    :class:`~langgraph.graph.StateGraph`; execution is
                    delegated to the inner graph's nodes.
* ``'Reference'`` — a node that is a pointer to another node (same thread).
                    Python code must call :func:`~backend.graph.utils.execution_log.resolve_node_reference`
                    to obtain the Typical/Subgraph node's info.

Registry
--------
Add entries here whenever a new node or subgraph is wired into
:func:`~backend.graph.builder.build_graph` or any inner subgraph builder.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Type literals matching the SQL CHECK constraint
# ---------------------------------------------------------------------------

NODE_TYPE_TYPICAL: str = "Typical"
NODE_TYPE_SUBGRAPH: str = "Subgraph"
NODE_TYPE_REFERENCE: str = "Reference"

# ---------------------------------------------------------------------------
# Registry: node_name → type
# ---------------------------------------------------------------------------
# Outer-graph nodes that wrap a compiled StateGraph are 'Subgraph'.
# All computation nodes (function/class callables) are 'Typical'.
# 'Reference' nodes are registered explicitly when introduced.

_NODE_TYPE_REGISTRY: dict[str, str] = {
    # ── Outer-graph graph containers ─────────────────────────────────────
    "mock_perf_graph": NODE_TYPE_SUBGRAPH,
    "mock_single_graph": NODE_TYPE_SUBGRAPH,
    "fin_analyst_graph": NODE_TYPE_SUBGRAPH,
    # ── Outer-graph typical nodes (direct callables) ─────────────────────────
    "mock_analysis": NODE_TYPE_TYPICAL,
    "mock_report": NODE_TYPE_TYPICAL,
    # ── mock_perf inner nodes ────────────────────────────────────────────────
    "perf_runner": NODE_TYPE_TYPICAL,
    "query_node": NODE_TYPE_TYPICAL,
    "news_node": NODE_TYPE_TYPICAL,
    "stats_node": NODE_TYPE_TYPICAL,
    "merge_node": NODE_TYPE_TYPICAL,
    # ── mock_single inner nodes ──────────────────────────────────────────────
    "query": NODE_TYPE_TYPICAL,
    "mock_news": NODE_TYPE_TYPICAL,
    "mock_stats": NODE_TYPE_TYPICAL,
    "merge": NODE_TYPE_TYPICAL,
    # ── fin_analyst inner nodes ──────────────────────────────────────────────
    "fin_analyst_runner": NODE_TYPE_TYPICAL,
}

# ---------------------------------------------------------------------------
# Subgraph membership: maps each subgraph name to its direct inner nodes.
# Used to derive node_type and subgraph_parent at SSE emit time.
# ---------------------------------------------------------------------------
_GRAPH_MEMBERS: dict[str, list[str]] = {
    "mock_perf_graph": ["perf_runner", "query_node", "news_node", "stats_node", "merge_node"],
    "mock_single_graph": ["query", "mock_news", "mock_stats", "merge"],
    "fin_analyst_graph": ["fin_analyst_runner"],
}

# Reverse map: inner node name → parent graph name
_NODE_GRAPH_PARENT: dict[str, str] = {
    member: graph
    for graph, members in _GRAPH_MEMBERS.items()
    for member in members
}


def get_node_type(node_name: str) -> str:
    """Return the type classification for *node_name*.

    Defaults to ``'Typical'`` for any node not explicitly registered, so new
    nodes added to the graph are always safe without requiring a registry update
    first.

    Args:
        node_name: The LangGraph node name as registered with ``add_node()``.

    Returns:
        One of ``'Typical'``, ``'Subgraph'``, or ``'Reference'``.
    """
    return _NODE_TYPE_REGISTRY.get(node_name, NODE_TYPE_TYPICAL)


def get_graph_members(graph_name: str) -> list[str]:
    """Return the list of inner node names for a given graph container.

    Args:
        graph_name: The LangGraph graph container node name.

    Returns:
        List of inner node name strings; empty list for unknown graphs.
    """
    return _GRAPH_MEMBERS.get(graph_name, [])


def get_node_graph_parent(node_name: str) -> str | None:
    """Return the graph container name that owns *node_name*, or ``None`` for outer nodes.

    Args:
        node_name: A LangGraph node name.

    Returns:
        The parent graph container name string, or ``None`` if the node is not an inner node.
    """
    return _NODE_GRAPH_PARENT.get(node_name)


__all__ = [
    "NODE_TYPE_TYPICAL",
    "NODE_TYPE_SUBGRAPH",
    "NODE_TYPE_REFERENCE",
    "get_node_type",
    "get_graph_members",
    "get_node_graph_parent",
]
