"""Graph builders — two-level routed graph.

Topology::

    Outer graph:
        START → (conditional route) → mock_perf_subgraph | mock_single_subgraph | fin_analyst_subgraph → …
        mock_single_subgraph → mock_analysis → mock_report → END   (both are outer-graph nodes)
        mock_perf_subgraph → END
        fin_analyst_subgraph → END

    mock_perf_subgraph (compiled by build_mock_perf_subgraph()):
        perf-test path:   START → perf_runner → END

    mock_single_subgraph (compiled by build_mock_single_subgraph()):
        prep path:        START → query_node → [mock_news, mock_stats] → merge_node → END
        NOTE: mock_analysis and mock_report are NOT in this subgraph — see below.

    mock_analysis (direct outer-graph node):
        Wired as: mock_single_subgraph → mock_analysis → mock_report

    mock_report (direct outer-graph node):
        Wired as: mock_analysis → mock_report → END
        No ``interrupt()`` is used — pause handled by direct asyncio.Task.cancel().

    fin_analyst_subgraph:
        START → fin_analyst_runner → END

Routing is query-text driven:

    ``"DO STREAMING PERFORMANCE TEST NOW"``  → mock_perf_subgraph
    ``"DO E2E TEST NOW"``                    → mock_single_subgraph → mock_analysis → mock_report
    all other queries                        → fin_analyst_subgraph
"""

from __future__ import annotations

from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from backend.graph.agents.mock_perf import PERF_TEST_TRIGGER
from backend.graph.agents.mock_single import MOCK_SINGLE_TRIGGER
from backend.graph.state import StreamRunState


def _build_subgraphs() -> dict[str, Any]:
    """Build and compile all agent subgraphs.

    Returns:
        Dict mapping subgraph node name to its compiled ``StateGraph``.
    """
    from backend.graph.agents.mock_perf import build_mock_perf_subgraph  # noqa: PLC0415
    from backend.graph.agents.mock_single import build_mock_single_subgraph  # noqa: PLC0415
    from backend.graph.agents.fin_analyst import fin_analyst_runner  # noqa: PLC0415

    analyst_inner = StateGraph(StreamRunState)
    analyst_inner.add_node("fin_analyst_runner", fin_analyst_runner)
    analyst_inner.add_edge(START, "fin_analyst_runner")
    analyst_inner.add_edge("fin_analyst_runner", END)

    return {
        "mock_perf_subgraph": build_mock_perf_subgraph(),
        "mock_single_subgraph": build_mock_single_subgraph(),
        "fin_analyst_subgraph": analyst_inner.compile(),
    }


def _route_query(subgraphs: dict[str, Any]) -> Callable[[StreamRunState], Any]:
    """Factory: return a routing function that resolves to the compiled subgraph.

    The perf-test trigger phrase may be followed by additional metadata appended
    by the frontend (e.g. ``" - Stream #1 [run-uuid]"``) so the dedup index
    never collides across concurrent sessions.  A ``startswith`` check covers
    all such variants.

    Args:
        subgraphs: Dict mapping node name to compiled subgraph, from ``_build_subgraphs``.

    Returns:
        A routing function that returns the compiled subgraph for the given state.
    """
    def _router(state: StreamRunState) -> Any:
        query: str = state.get("query", "").strip().upper()
        if query.startswith(PERF_TEST_TRIGGER):
            return subgraphs["mock_perf_subgraph"]
        if query.startswith(MOCK_SINGLE_TRIGGER):
            return subgraphs["mock_single_subgraph"]
        return subgraphs["fin_analyst_subgraph"]

    return _router


def build_graph() -> StateGraph:
    """Construct the two-level routed graph (uncompiled).

    The outer graph conditionally routes to one of three compiled inner graphs:

    * ``mock_perf_subgraph``   — performance-test mock streaming pipeline.
    * ``mock_single_subgraph`` — single-run complex subgraph for graph visualization.
    * ``fin_analyst_subgraph`` — financial analysis agent.

    Returns:
        The outer :class:`~langgraph.graph.StateGraph` ready to be compiled
        with a checkpointer.
    """
    from backend.graph.agents.mock_single.nodes.analysis_node import mock_analysis_node  # noqa: PLC0415
    from backend.graph.agents.mock_single.nodes.report_node import mock_report_node  # noqa: PLC0415

    subgraphs = _build_subgraphs()
    router = _route_query(subgraphs)

    outer = StateGraph(StreamRunState)
    for name, graph in subgraphs.items():
        outer.add_node(name, graph)
    # mock_analysis and mock_report are direct outer-graph nodes (NOT inside
    # mock_single_subgraph) to avoid the nested-subgraph resume bug.
    outer.add_node("mock_analysis", mock_analysis_node)
    outer.add_node("mock_report", mock_report_node)
    outer.add_conditional_edges(
        START,
        router,
        {graph: name for name, graph in subgraphs.items()},
    )
    outer.add_edge("mock_perf_subgraph", END)
    outer.add_edge("mock_single_subgraph", "mock_analysis")
    outer.add_edge("mock_analysis", "mock_report")
    outer.add_edge("mock_report", END)
    outer.add_edge("fin_analyst_subgraph", END)

    return outer
