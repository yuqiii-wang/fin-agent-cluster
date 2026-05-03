"""mock_single.graph — LangGraph subgraph builder for the mock single-request agent.

Preparation pipeline (trigger: ``"DO E2E TEST NOW"``)::

    START → query → [mock_news, mock_stats] → merge → END

The ``mock_analysis`` node is intentionally kept OUT of this subgraph and wired
directly to the outer routing graph in :func:`~backend.graph.builder.build_graph`.

The subgraph is compiled with ``checkpointer=True`` so it inherits the parent
PostgresSaver and saves a checkpoint after each internal node step.  This
enables time-travel replay from mid-subgraph nodes (query, mock_news,
mock_stats, merge) without requiring a raw namespace scan at invocation time.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.graph.state import StreamRunState

#: Trigger phrase for the single-run analysis pipeline.
MOCK_SINGLE_TRIGGER: str = "DO E2E TEST NOW"


def build_mock_single_subgraph() -> StateGraph:
    """Construct and compile the mock single-request prep subgraph.

    Builds the data-gathering fan-out pipeline::

        START → query → [mock_news, mock_stats] → merge → END

    ``mock_analysis`` is NOT included here — it is wired as a direct node in
    the outer graph so ``interrupt()`` inside it works at the outer checkpoint
    level, avoiding the nested-subgraph resume bug.

    Returns:
        Compiled :class:`~langgraph.graph.StateGraph`.
    """
    from backend.graph.agents.mock_single.nodes import (  # noqa: PLC0415
        merge_node,
        mock_news_node,
        query_node,
        mock_stats_node,
    )

    g = StateGraph(StreamRunState)

    g.add_node("query", query_node)
    g.add_node("mock_news", mock_news_node)
    g.add_node("mock_stats", mock_stats_node)
    g.add_node("merge", merge_node)

    g.add_edge(START, "query")
    g.add_edge("query", "mock_news")
    g.add_edge("query", "mock_stats")
    g.add_edge("mock_news", "merge")
    g.add_edge("mock_stats", "merge")
    g.add_edge("merge", END)

    # checkpointer=True: inherit parent's AsyncPostgresSaver so each internal
    # node (query, mock_news, mock_stats, merge) gets its own checkpoint in
    # the subgraph namespace, enabling per-node time-travel replay.
    return g.compile(checkpointer=True)


__all__ = ["build_mock_single_subgraph", "MOCK_SINGLE_TRIGGER"]

