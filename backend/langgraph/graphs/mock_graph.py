"""Mock graph — full multi-node fin-analysis graph used in test mode.

Renamed from ``backend.langgraph.graph`` and relocated under
``backend.langgraph.graphs``.  This graph contains the complete node
topology (query → regional → research → stats/news → conclusion) and is
used when ``Settings.TEST_MODE`` is ``True`` so integration and load tests
can exercise the full pipeline against mock data.

Graph topology
--------------

Regional routing (8-hour UTC windows)
--------------------------------------
  APAC: UTC 00:00-07:59 — Tokyo, Hong Kong, Shanghai, Singapore, Sydney
  EMEA: UTC 08:00-15:59 — London, Euronext, Deutsche Börse, SIX, OMX
  AMER: UTC 16:00-23:59 — NYSE, NASDAQ, TSX, B3, BMV

Thread → Node → Task hierarchy
-------------------------------
Each LangGraph node function:
  1. Calls ``upsert_node`` to register itself in ``fin_agents.nodes``.
  2. Invokes one or more ``@task``-decorated functions.
  3. Each ``@task`` calls ``create_task``, delegates to a Celery worker,
     then calls ``complete_task``.
  4. ``complete_task`` auto-calls ``complete_node`` when all tasks in the
     node are terminal — emitting a ``node_status`` SSE event to the UI.

SSE event flow
--------------
  task_status: running
  task_status: completed  (or failed)
  node_status: completed  ← auto-emitted when all tasks are done
  ... (repeat for each node / task)
  thread-level done  ← emitted by the caller after ainvoke returns

Persistence
-----------
  fin_agents.nodes        — one row per node execution
  fin_agents.tasks        — one row per task execution
  fin_agents.llm_responses — one row per streaming LLM call (conclusion)
  fin_agents.checkpoints  — LangGraph checkpoint (via AsyncPostgresSaver)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from langgraph.graph import StateGraph, START, END

from backend.langgraph.state import GraphState
from backend.langgraph.nodes.mock_query_node import query_node
from backend.langgraph.nodes.mock_regional_analyze_nodes import (
    apac_analyze_node,
    emea_analyze_node,
    amer_analyze_node,
)
from backend.langgraph.nodes.mock_research_subgraph import research_subgraph
from backend.langgraph.nodes.mock_analyze_stats_node import analyze_stats_node
from backend.langgraph.nodes.mock_analyze_news_node import analyze_news_node
from backend.langgraph.nodes.mock_conclusion_node import conclusion_node

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regional routing
# ---------------------------------------------------------------------------

_APAC_START_HOUR = 0
_EMEA_START_HOUR = 8
_AMER_START_HOUR = 16


def _route_to_region(state: GraphState) -> str:
    """Select the regional analyze node based on current UTC business hour.

    Divides the 24-hour UTC clock into three equal 8-hour windows:
      * APAC — UTC 00:00-07:59
      * EMEA — UTC 08:00-15:59
      * AMER — UTC 16:00-23:59

    Args:
        state: Current ``GraphState`` (unused; routing is time-based).

    Returns:
        LangGraph node name string for the selected regional node.
    """
    hour = datetime.now(timezone.utc).hour

    if _APAC_START_HOUR <= hour < _EMEA_START_HOUR:
        return "apac_analyze_node"
    elif _EMEA_START_HOUR <= hour < _AMER_START_HOUR:
        return "emea_analyze_node"
    else:
        return "amer_analyze_node"


def build_graph_builder() -> StateGraph:
    """Construct the mock fin-analysis StateGraph (uncompiled).

    Returns a ``StateGraph`` with all nodes and edges configured but not yet
    compiled.  Call ``.compile(checkpointer=...)`` on the result to attach a
    checkpointer before use.

    Returns:
        Uncompiled :class:`~langgraph.graph.StateGraph`.
    """
    builder = StateGraph(GraphState)

    # ── Nodes ───────────────────────────────────────────────────────────
    builder.add_node("query_node", query_node)
    builder.add_node("apac_analyze_node", apac_analyze_node)
    builder.add_node("emea_analyze_node", emea_analyze_node)
    builder.add_node("amer_analyze_node", amer_analyze_node)
    builder.add_node("research_subgraph", research_subgraph)
    builder.add_node("analyze_stats_node", analyze_stats_node)
    builder.add_node("analyze_news_node", analyze_news_node)
    builder.add_node("conclusion_node", conclusion_node)

    # ── Edges ───────────────────────────────────────────────────────────
    builder.add_edge(START, "query_node")

    # Conditional fork: route to the matching regional analyze node
    builder.add_conditional_edges(
        "query_node",
        _route_to_region,
        {
            "apac_analyze_node": "apac_analyze_node",
            "emea_analyze_node": "emea_analyze_node",
            "amer_analyze_node": "amer_analyze_node",
        },
    )

    # All three regional paths merge into research_subgraph
    builder.add_edge("apac_analyze_node", "research_subgraph")
    builder.add_edge("emea_analyze_node", "research_subgraph")
    builder.add_edge("amer_analyze_node", "research_subgraph")

    # Fan-out: research_subgraph triggers both parallel analysis nodes.
    builder.add_edge("research_subgraph", "analyze_stats_node")
    builder.add_edge("research_subgraph", "analyze_news_node")

    # Fan-in: LangGraph waits for all incoming edges before executing conclusion_node.
    builder.add_edge("analyze_stats_node", "conclusion_node")
    builder.add_edge("analyze_news_node", "conclusion_node")
    builder.add_edge("conclusion_node", END)

    return builder


def build_graph() -> StateGraph:
    """Construct and compile the mock fin-analysis StateGraph without a checkpointer.

    Returns:
        Compiled :class:`~langgraph.graph.StateGraph`.
    """
    return build_graph_builder().compile()


# Module-level compiled graph — import and use directly, or call build_graph()
# to get a fresh instance with a custom checkpointer.
fin_analysis_graph = build_graph()


async def run_analysis(
    thread_id: str,
    user_id: str,
    query: str,
    checkpointer: Any = None,
) -> GraphState:
    """Run the mock fin-analysis graph for a single user query.

    This is the primary entry-point for API handlers in test mode.  It:
    1. Optionally attaches a postgres checkpointer for fault-tolerance.
    2. Invokes the graph with the initial state.
    3. Returns the final :class:`~backend.langgraph.state.GraphState`.

    The caller is responsible for:
    - Inserting the ``fin_agents.user_queries`` row *before* calling this.
    - Publishing the thread-level ``done`` SSE event *after* this returns.

    Args:
        thread_id:    LangGraph thread UUID (must already exist in user_queries).
        user_id:      Authenticated user identifier.
        query:        Raw user query string.
        checkpointer: Optional ``AsyncPostgresSaver`` instance.  When ``None``
                      the module-level ``fin_analysis_graph`` is used without
                      checkpointing.

    Returns:
        Final :class:`~backend.langgraph.state.GraphState` after the graph
        completes.
    """
    initial_state: GraphState = {
        "thread_id": thread_id,
        "user_id": user_id,
        "query": query,
    }
    config = {"configurable": {"thread_id": thread_id}}

    if checkpointer is not None:
        graph = build_graph_builder().compile(checkpointer=checkpointer)
    else:
        graph = fin_analysis_graph

    logger.info("[mock_graph] starting thread_id=%s query=%r", thread_id, query[:80])

    from backend.langgraph.lifecycle import register_thread
    register_thread(thread_id)

    final_state: GraphState = await graph.ainvoke(initial_state, config=config)
    logger.info(
        "[mock_graph] completed thread_id=%s conclusion_len=%d",
        thread_id, len(final_state.get("conclusion") or ""),
    )
    return final_state


__all__ = ["build_graph_builder", "build_graph", "fin_analysis_graph", "run_analysis"]
