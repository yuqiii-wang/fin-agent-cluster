"""backend.langgraph.compiled — process-wide compiled LangGraph instance.

Pre-compiles the fin-analysis graph with a pooled ``AsyncPostgresSaver``
checkpointer once at startup so individual query handlers avoid the
per-invocation rebuild cost (~5–20 ms) and cold DB connect overhead.

Usage::

    from backend.langgraph.compiled import get_compiled_graph, init_compiled_graph

    await init_compiled_graph()   # called once from app lifespan
    graph = get_compiled_graph()  # retrieved per-query handler
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_compiled_graph: Any | None = None


async def init_compiled_graph() -> None:
    """Compile the fin-analysis graph with the pooled checkpointer and cache it.

    Must be called once during FastAPI lifespan startup after connection pools
    are open.  Subsequent calls are no-ops.
    """
    global _compiled_graph
    if _compiled_graph is not None:
        return

    from backend.db.postgres.checkpointer import ensure_setup, get_pool_checkpointer
    from langgraph.graph import StateGraph, START, END
    from backend.langgraph.state import GraphState
    from backend.langgraph.nodes.query_node import query_node
    from backend.langgraph.nodes.research_subgraph import research_subgraph
    from backend.langgraph.nodes.conclusion_node import conclusion_node

    # Ensure checkpointer tables exist cluster-wide (Redis-locked, idempotent).
    await ensure_setup()

    pg_checkpointer = get_pool_checkpointer()

    builder = StateGraph(GraphState)
    builder.add_node("query_node", query_node)
    builder.add_node("research_subgraph", research_subgraph)
    builder.add_node("conclusion_node", conclusion_node)
    builder.add_edge(START, "query_node")
    builder.add_edge("query_node", "research_subgraph")
    builder.add_edge("research_subgraph", "conclusion_node")
    builder.add_edge("conclusion_node", END)

    _compiled_graph = builder.compile(checkpointer=pg_checkpointer)
    logger.info("[langgraph.compiled] graph compiled with pooled AsyncPostgresSaver")


def get_compiled_graph() -> Any:
    """Return the cached compiled graph.

    Raises:
        RuntimeError: If called before :func:`init_compiled_graph`.
    """
    if _compiled_graph is None:
        raise RuntimeError(
            "Compiled graph not initialised — call init_compiled_graph() during startup"
        )
    return _compiled_graph


__all__ = ["get_compiled_graph", "init_compiled_graph"]
