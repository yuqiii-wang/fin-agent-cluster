"""Fin-trading graph — production graph with a single query node (initial version).

This is the production graph used when ``Settings.TEST_MODE`` is ``False``.
The graph will be expanded with more nodes as the fin-trading pipeline is
built out.  Currently it contains only the real ``query_node`` (LLM-backed)
to establish the scaffold.

Graph topology (current)
-------------------------
  START → query_node → END

Thread → Node → Task hierarchy
-------------------------------
Each LangGraph node function:
  1. Calls ``upsert_node`` to register itself in ``fin_agents.nodes``.
  2. Invokes one or more ``@task``-decorated functions.
  3. Each ``@task`` calls ``create_task``, delegates to a Celery worker,
     then calls ``complete_task``.
  4. ``complete_task`` auto-calls ``complete_node`` when all tasks in the
     node are terminal — emitting a ``node_status`` SSE event to the UI.

Persistence
-----------
  fin_agents.nodes       — one row per node execution
  fin_agents.tasks       — one row per task execution
  fin_agents.checkpoints — LangGraph checkpoint (via AsyncPostgresSaver)
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import StateGraph, START, END

from backend.langgraph.state import GraphState
from backend.langgraph.nodes.query_node import query_node

logger = logging.getLogger(__name__)


def build_graph_builder() -> StateGraph:
    """Construct the fin-trading StateGraph (uncompiled).

    Returns a ``StateGraph`` with all nodes and edges configured but not yet
    compiled.  Call ``.compile(checkpointer=...)`` on the result to attach a
    checkpointer before use.

    Returns:
        Uncompiled :class:`~langgraph.graph.StateGraph`.
    """
    builder = StateGraph(GraphState)

    builder.add_node("query_node", query_node)

    builder.add_edge(START, "query_node")
    builder.add_edge("query_node", END)

    return builder


def build_graph() -> StateGraph:
    """Construct and compile the fin-trading StateGraph without a checkpointer.

    Returns:
        Compiled :class:`~langgraph.graph.StateGraph`.
    """
    return build_graph_builder().compile()


# Module-level compiled graph — import and use directly, or call build_graph()
# to get a fresh instance with a custom checkpointer.
fin_trading_graph = build_graph()


async def run_analysis(
    thread_id: str,
    user_id: str,
    query: str,
    checkpointer: Any = None,
) -> GraphState:
    """Run the fin-trading graph for a single user query.

    This is the primary entry-point for API handlers in production mode.  It:
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
                      the module-level ``fin_trading_graph`` is used without
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
        graph = fin_trading_graph

    logger.info("[fin_trading_graph] starting thread_id=%s query=%r", thread_id, query[:80])

    from backend.langgraph.lifecycle import register_thread
    register_thread(thread_id)

    final_state: GraphState = await graph.ainvoke(initial_state, config=config)
    logger.info(
        "[fin_trading_graph] completed thread_id=%s",
        thread_id,
    )
    return final_state


__all__ = ["build_graph_builder", "build_graph", "fin_trading_graph", "run_analysis"]
