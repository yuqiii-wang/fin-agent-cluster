"""Graph builders — two-level routed graph.

Topology::

    Outer graph:
        START → (conditional route) → mock_perf_subgraph | mock_single_subgraph | fin_analyst_subgraph → …
        mock_single_subgraph → mock_analysis → END   (mock_analysis is an outer-graph node)
        mock_perf_subgraph → END
        fin_analyst_subgraph → END

    mock_perf_subgraph (compiled by build_mock_perf_subgraph()):
        perf-test path:   START → perf_runner → END
        analysis path:    START → query_node → [news_node, stats_node] → merge_node → END

    mock_single_subgraph (compiled by build_mock_single_subgraph()):
        prep path:        START → query_node → [mock_news, mock_stats] → merge_node → END
        NOTE: mock_analysis is NOT in this subgraph — see below.

    mock_analysis (direct outer-graph node):
        Wired as: mock_single_subgraph → mock_analysis → END
        No ``interrupt()`` is used here — pause is handled by direct
        ``asyncio.Task.cancel()`` in ``pause_query``.  Using ``interrupt()``
        in an outer-graph node with ``@task`` caused ``Command(resume=True)``
        to load an earlier checkpoint and loop back through the subgraph.

    fin_analyst_subgraph:
        START → fin_analyst_runner → END

Routing is query-text driven:

    ``"DO STREAMING PERFORMANCE TEST NOW"``  → mock_perf_subgraph (perf_runner path)
    ``"DO MOCK ANALYSIS NOW"``               → mock_perf_subgraph (analysis path)
    ``"DO E2E TEST NOW"``                    → mock_single_subgraph → mock_analysis
    all other queries                        → fin_analyst_subgraph
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.graph.agents.mock_perf import MOCK_ANALYSIS_TRIGGER, PERF_TEST_TRIGGER
from backend.graph.agents.mock_single import MOCK_SINGLE_TRIGGER
from backend.graph.state import StreamRunState


def _route_query(state: StreamRunState) -> str:
    """Select the agent sub-graph based on query text.

    The perf-test trigger phrase may be followed by additional metadata appended
    by the frontend (e.g. ``" - Stream #1 [run-uuid]"``) so the dedup index
    never collides across concurrent sessions.  A ``startswith`` check covers
    all such variants.

    Args:
        state: Current graph state carrying the user ``query``.

    Returns:
        ``"mock_perf_subgraph"`` for perf/analysis trigger phrases,
        ``"mock_single_subgraph"`` for single-test trigger phrase,
        ``"fin_analyst_subgraph"`` for all other queries.
    """
    query: str = state.get("query", "").strip().upper()
    if query.startswith(PERF_TEST_TRIGGER) or query.startswith(MOCK_ANALYSIS_TRIGGER):
        return "mock_perf_subgraph"
    if query.startswith(MOCK_SINGLE_TRIGGER):
        return "mock_single_subgraph"
    return "fin_analyst_subgraph"


def build_graph() -> StateGraph:
    """Construct the two-level routed graph (uncompiled).

    The outer graph conditionally routes to one of three compiled inner graphs:

    * ``mock_perf_subgraph``   — performance-test mock streaming and analysis pipeline.
    * ``mock_single_subgraph`` — single-run complex subgraph for graph visualization.
    * ``fin_analyst_subgraph`` — financial analysis agent.

    Returns:
        The outer :class:`~langgraph.graph.StateGraph` ready to be compiled
        with a checkpointer.
    """
    from backend.graph.agents.mock_perf import build_mock_perf_subgraph  # noqa: PLC0415
    from backend.graph.agents.mock_single import build_mock_single_subgraph  # noqa: PLC0415
    from backend.graph.agents.mock_single.nodes.analysis_node import mock_analysis_node  # noqa: PLC0415
    from backend.graph.agents.fin_analyst import fin_analyst_runner  # noqa: PLC0415

    # ── Mock-perf inner sub-graph ────────────────────────────────────────
    compiled_mock_perf = build_mock_perf_subgraph()

    # ── Mock-single inner sub-graph (prep: query→news→stats→merge) ─────────────
    compiled_mock_single = build_mock_single_subgraph()

    # ── Fin-analyst inner sub-graph ────────────────────────────────────────
    analyst_inner = StateGraph(StreamRunState)
    analyst_inner.add_node("fin_analyst_runner", fin_analyst_runner)
    analyst_inner.add_edge(START, "fin_analyst_runner")
    analyst_inner.add_edge("fin_analyst_runner", END)
    compiled_analyst = analyst_inner.compile()

    # ── Outer graph with conditional routing ──────────────────────────────
    outer = StateGraph(StreamRunState)
    outer.add_node("mock_perf_subgraph", compiled_mock_perf)
    outer.add_node("mock_single_subgraph", compiled_mock_single)
    outer.add_node("fin_analyst_subgraph", compiled_analyst)
    # mock_analysis is a direct outer-graph node (NOT inside mock_single_subgraph).
    outer.add_node("mock_analysis", mock_analysis_node)
    outer.add_conditional_edges(START, _route_query, {
        "mock_perf_subgraph": "mock_perf_subgraph",
        "mock_single_subgraph": "mock_single_subgraph",
        "fin_analyst_subgraph": "fin_analyst_subgraph",
    })
    outer.add_edge("mock_perf_subgraph", END)
    outer.add_edge("mock_single_subgraph", "mock_analysis")
    outer.add_edge("mock_analysis", END)
    outer.add_edge("fin_analyst_subgraph", END)

    return outer
