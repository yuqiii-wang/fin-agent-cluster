"""Graph builders — assembles the financial analysis graphs.

Financial analysis topology::

    START → query_optimizer → market_data_collector → decision_maker → END

Performance-test topology::

    START → perf_test_streamer → END

Unified graph topology::

    START → (router: perf test trigger?) → perf_test_streamer → END
                                         → query_optimizer → market_data_collector → decision_maker → END
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.graph.agents.decision_maker import decision_maker
from backend.graph.agents.market_data import market_data_collector
from backend.graph.agents.perf_test import perf_test_streamer
from backend.graph.agents.query_optimizer import query_optimizer
from backend.graph.state import FinAnalysisState, PerfTestState, UnifiedGraphState

#: Exact query string that triggers the perf-test branch in the unified graph.
PERF_TEST_TRIGGER: str = "DO STREAMING PERFORMANCE TEST NOW"


def build_graph() -> StateGraph:
    """Construct the 3-node financial analysis graph (uncompiled).

    Returns:
        A :class:`~langgraph.graph.StateGraph` ready to be compiled with a
        checkpointer and served via FastAPI.
    """
    builder = StateGraph(FinAnalysisState)

    builder.add_node("query_optimizer", query_optimizer)
    builder.add_node("market_data_collector", market_data_collector)
    builder.add_node("decision_maker", decision_maker)

    builder.add_edge(START, "query_optimizer")
    builder.add_edge("query_optimizer", "market_data_collector")
    builder.add_edge("market_data_collector", "decision_maker")
    builder.add_edge("decision_maker", END)

    return builder


def build_streaming_perf_test_graph() -> StateGraph:
    """Construct the single-node streaming performance-test graph (uncompiled).

    Topology::

        START → perf_test_streamer → END

    The node reads mock tokens from the Celery-produced Redis Stream and pipes
    them through :func:`~backend.graph.utils.task_stream.stream_text_task`,
    producing identical ``started / token / completed`` SSE events to any real
    LangGraph node.

    Returns:
        A :class:`~langgraph.graph.StateGraph` ready to be compiled.
    """
    builder = StateGraph(PerfTestState)
    builder.add_node("perf_test_streamer", perf_test_streamer)
    builder.add_edge(START, "perf_test_streamer")
    builder.add_edge("perf_test_streamer", END)
    return builder


def _route_query(state: UnifiedGraphState) -> str:
    """Return the first node to run based on whether the query is a perf test.

    Args:
        state: Unified graph state containing the ``query`` field.

    Returns:
        ``"perf_test_streamer"`` for the perf-test trigger; otherwise
        ``"query_optimizer"`` to start the fin-analysis pipeline.
    """
    if state.get("query", "").strip() == PERF_TEST_TRIGGER:
        return "perf_test_streamer"
    return "query_optimizer"


def build_unified_graph() -> StateGraph:
    """Construct the unified parent graph that routes to either the fin-analysis
    pipeline or the perf-test node (uncompiled).

    Topology::

        START ──(perf test trigger?)──► perf_test_streamer ──► END
              └──────────────────────► query_optimizer ──► market_data_collector
                                           ──► decision_maker ──► END

    Routing is done by :func:`_route_query` at the START edge so both branches
    share a single Celery task (``run_graph``) and a single per-thread Redis
    queue — no separate runner or asyncio.Task needed for the perf-test path.

    Returns:
        A :class:`~langgraph.graph.StateGraph` ready to be compiled with a
        checkpointer and served via the Celery ``run_graph`` worker.
    """
    builder = StateGraph(UnifiedGraphState)

    builder.add_node("query_optimizer", query_optimizer)
    builder.add_node("market_data_collector", market_data_collector)
    builder.add_node("decision_maker", decision_maker)
    builder.add_node("perf_test_streamer", perf_test_streamer)

    builder.add_conditional_edges(
        START,
        _route_query,
        {
            "query_optimizer": "query_optimizer",
            "perf_test_streamer": "perf_test_streamer",
        },
    )

    # Fin-analysis pipeline
    builder.add_edge("query_optimizer", "market_data_collector")
    builder.add_edge("market_data_collector", "decision_maker")
    builder.add_edge("decision_maker", END)

    # Perf-test path
    builder.add_edge("perf_test_streamer", END)

    return builder
