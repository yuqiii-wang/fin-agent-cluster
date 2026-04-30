"""Graph builders — two-level routed graph.

Topology::

    Outer graph:
        START → (conditional route) → stream_subgraph | fin_analyst_subgraph → END

    stream_subgraph (inner graph — triggered by perf-test query):
        START → stream_runner → END

    fin_analyst_subgraph (inner graph — all other queries):
        START → fin_analyst_runner → END

Routing is query-text driven:

    ``"DO STREAMING PERFORMANCE TEST NOW"``  → stream_subgraph
    all other queries                        → fin_analyst_subgraph

The compiled outer graph is initialised once at startup via
:func:`~backend.graph.compiled.init_compiled_graph`.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.graph.state import StreamRunState

#: Exact trigger phrase (case-insensitive comparison) to activate the perf-test streamer.
PERF_TEST_TRIGGER: str = "DO STREAMING PERFORMANCE TEST NOW"


def _route_query(state: StreamRunState) -> str:
    """Select the agent sub-graph based on query text.

    The perf-test trigger phrase may be followed by additional metadata appended
    by the frontend (e.g. ``" - Stream #1 [run-uuid]"``) so the dedup index
    never collides across concurrent sessions.  A ``startswith`` check covers
    all such variants.

    Args:
        state: Current graph state carrying the user ``query``.

    Returns:
        ``"stream_subgraph"`` for the perf-test trigger,
        ``"fin_analyst_subgraph"`` for all other queries.
    """
    query: str = state.get("query", "")
    if query.strip().upper().startswith(PERF_TEST_TRIGGER):
        return "stream_subgraph"
    return "fin_analyst_subgraph"


def build_graph() -> StateGraph:
    """Construct the two-level routed graph (uncompiled).

    The outer graph conditionally routes to one of two compiled inner graphs:

    * ``stream_subgraph`` — performance-test streamer (Celery ingest).
    * ``fin_analyst_subgraph`` — financial analysis agent.

    Returns:
        The outer :class:`~langgraph.graph.StateGraph` ready to be compiled
        with a checkpointer.
    """
    from backend.graph.agents.streamer import stream_runner  # noqa: PLC0415
    from backend.graph.agents.fin_analyst import fin_analyst_runner  # noqa: PLC0415

    # ── Streamer inner sub-graph ───────────────────────────────────────────
    streamer_inner = StateGraph(StreamRunState)
    streamer_inner.add_node("stream_runner", stream_runner)
    streamer_inner.add_edge(START, "stream_runner")
    streamer_inner.add_edge("stream_runner", END)
    compiled_streamer = streamer_inner.compile()

    # ── Fin-analyst inner sub-graph ────────────────────────────────────────
    analyst_inner = StateGraph(StreamRunState)
    analyst_inner.add_node("fin_analyst_runner", fin_analyst_runner)
    analyst_inner.add_edge(START, "fin_analyst_runner")
    analyst_inner.add_edge("fin_analyst_runner", END)
    compiled_analyst = analyst_inner.compile()

    # ── Outer graph with conditional routing ──────────────────────────────
    outer = StateGraph(StreamRunState)
    outer.add_node("stream_subgraph", compiled_streamer)
    outer.add_node("fin_analyst_subgraph", compiled_analyst)
    outer.add_conditional_edges(START, _route_query, {
        "stream_subgraph": "stream_subgraph",
        "fin_analyst_subgraph": "fin_analyst_subgraph",
    })
    outer.add_edge("stream_subgraph", END)
    outer.add_edge("fin_analyst_subgraph", END)

    return outer
