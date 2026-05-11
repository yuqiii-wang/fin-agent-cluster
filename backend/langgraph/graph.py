"""Fin-analysis LangGraph — main graph definition.

Graph topology
--------------

  START
    │
    ▼
  query_node          ← single task: analyze_query
    │
    ▼
  research_subgraph   ← Subgraph containing three nodes:
    │   ┌──────────────────────────────────────────┐
    │   │  stats_node ──┐                          │
    │   │               ├─► merge_node             │
    │   │  news_node ───┘                          │
    │   └──────────────────────────────────────────┘
    │
    ▼
  conclusion_node     ← single streaming task: stream_conclusion
    │
    ▼
  END

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
from typing import Any

from langgraph.graph import StateGraph, START, END

from backend.langgraph.state import GraphState
from backend.langgraph.nodes.query_node import query_node
from backend.langgraph.nodes.research_subgraph import research_subgraph
from backend.langgraph.nodes.conclusion_node import conclusion_node

logger = logging.getLogger(__name__)


def build_graph() -> StateGraph:
    """Construct and compile the fin-analysis StateGraph.

    The graph is compiled without a checkpointer here; callers should attach
    one (e.g. ``AsyncPostgresSaver``) at invocation time via
    ``graph.compile(checkpointer=...)``.

    Returns:
        Compiled :class:`~langgraph.graph.StateGraph` ready for
        ``await graph.ainvoke(state, config)``.
    """
    builder = StateGraph(GraphState)

    # ── Nodes ───────────────────────────────────────────────────────────
    builder.add_node("query_node", query_node)
    builder.add_node("research_subgraph", research_subgraph)
    builder.add_node("conclusion_node", conclusion_node)

    # ── Edges ───────────────────────────────────────────────────────────
    builder.add_edge(START, "query_node")
    builder.add_edge("query_node", "research_subgraph")
    builder.add_edge("research_subgraph", "conclusion_node")
    builder.add_edge("conclusion_node", END)

    return builder.compile()


# Module-level compiled graph — import and use directly, or call build_graph()
# to get a fresh instance with a custom checkpointer.
fin_analysis_graph = build_graph()


async def run_analysis(
    thread_id: str,
    user_id: str,
    query: str,
    checkpointer: Any = None,
) -> GraphState:
    """Run the fin-analysis graph for a single user query.

    This is the primary entry-point for API handlers.  It:
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
        graph = build_graph()
        # Re-compile with the supplied checkpointer.
        from langgraph.graph import StateGraph
        builder = StateGraph(GraphState)
        builder.add_node("query_node", query_node)
        builder.add_node("research_subgraph", research_subgraph)
        builder.add_node("conclusion_node", conclusion_node)
        builder.add_edge(START, "query_node")
        builder.add_edge("query_node", "research_subgraph")
        builder.add_edge("research_subgraph", "conclusion_node")
        builder.add_edge("conclusion_node", END)
        graph = builder.compile(checkpointer=checkpointer)
    else:
        graph = fin_analysis_graph

    logger.info("[graph] starting thread_id=%s query=%r", thread_id, query[:80])

    # Register the cancel token before the graph starts so that any
    # concurrent cancel_thread() call can signal the delegation poll loops.
    from backend.langgraph.lifecycle import register_thread
    register_thread(thread_id)

    final_state: GraphState = await graph.ainvoke(initial_state, config=config)
    logger.info(
        "[graph] completed thread_id=%s conclusion_len=%d",
        thread_id, len(final_state.get("conclusion") or ""),
    )
    return final_state
