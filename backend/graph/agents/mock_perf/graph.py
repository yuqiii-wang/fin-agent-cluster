"""mock.graph — internal LangGraph subgraph builder for the mock perf agent.

Defines the perf-test pipeline:

Perf-test pipeline  (trigger: ``"DO STREAMING PERFORMANCE TEST NOW"``)
    START → perf_runner → END

The outer :func:`~backend.graph.builder.build_graph` routes the trigger to
this compiled subgraph.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.graph.state import StreamRunState

#: Trigger phrase for the streaming performance-test pipeline.
PERF_TEST_TRIGGER: str = "DO STREAMING PERFORMANCE TEST NOW"


def build_mock_perf_subgraph() -> StateGraph:
    """Construct and compile the mock perf agent subgraph.

    Returns:
        Compiled :class:`~langgraph.graph.StateGraph` implementing the
        perf-test pipeline.
    """
    from backend.graph.agents.mock_perf.nodes import perf_runner  # noqa: PLC0415

    g = StateGraph(StreamRunState)
    g.add_node("perf_runner", perf_runner)
    g.add_edge(START, "perf_runner")
    g.add_edge("perf_runner", END)

    return g.compile()


__all__ = ["build_mock_perf_subgraph", "PERF_TEST_TRIGGER"]
