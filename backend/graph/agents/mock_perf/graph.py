"""mock.graph — internal LangGraph subgraph builder for the mock agent.

Defines two pipelines activated by different trigger phrases:

Perf-test pipeline  (trigger: ``"DO STREAMING PERFORMANCE TEST NOW"``)
    START → perf_runner → END

Analysis pipeline  (trigger: ``"DO MOCK ANALYSIS NOW"``)
    START → query_node → [news_node, stats_node] → merge_node → END

The outer :func:`~backend.graph.builder.build_graph` routes both triggers to
this compiled subgraph.  Internal routing is handled by :func:`_route_mock`.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.graph.state import StreamRunState

#: Trigger phrase for the streaming performance-test pipeline.
PERF_TEST_TRIGGER: str = "DO STREAMING PERFORMANCE TEST NOW"

#: Trigger phrase for the mock multi-node analysis pipeline.
MOCK_ANALYSIS_TRIGGER: str = "DO MOCK ANALYSIS NOW"


def _route_mock(state: StreamRunState) -> str:
    """Route within the mock subgraph based on query text.

    Args:
        state: Current graph state.

    Returns:
        ``"perf_runner"`` for perf-test queries, ``"query_node"`` for analysis.
    """
    query: str = state.get("query", "").strip().upper()
    if query.startswith(PERF_TEST_TRIGGER):
        return "perf_runner"
    return "query_node"


def build_mock_perf_subgraph() -> StateGraph:
    """Construct and compile the mock agent internal subgraph.

    Returns:
        Compiled :class:`~langgraph.graph.StateGraph` implementing both
        the perf-test and analysis pipelines.
    """
    from backend.graph.agents.mock_perf.nodes import (  # noqa: PLC0415
        merge_node,
        mock_news_node,
        query_node,
        mock_stats_node,
        perf_runner,
    )

    g = StateGraph(StreamRunState)

    # Perf-test pipeline nodes.
    g.add_node("perf_runner", perf_runner)

    # Analysis pipeline nodes (fan-out / fan-in).
    g.add_node("query_node", query_node)
    g.add_node("news_node", mock_news_node)
    g.add_node("stats_node", mock_stats_node)
    g.add_node("merge_node", merge_node)

    # ── Routing ──────────────────────────────────────────────────────────────
    g.add_conditional_edges(
        START,
        _route_mock,
        {"perf_runner": "perf_runner", "query_node": "query_node"},
    )

    # ── Perf-test path ────────────────────────────────────────────────────────
    g.add_edge("perf_runner", END)

    # ── Analysis path (fan-out then fan-in) ───────────────────────────────────
    g.add_edge("query_node", "news_node")
    g.add_edge("query_node", "stats_node")
    g.add_edge("news_node", "merge_node")
    g.add_edge("stats_node", "merge_node")
    g.add_edge("merge_node", END)

    return g.compile()


__all__ = ["build_mock_perf_subgraph", "PERF_TEST_TRIGGER", "MOCK_ANALYSIS_TRIGGER"]
