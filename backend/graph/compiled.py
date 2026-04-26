"""Pre-compiled LangGraph graph singleton.

The unified graph is compiled fresh at every application startup using a
pooled :class:`~langgraph.checkpoint.postgres.aio.AsyncPostgresSaver`.  Any
previously compiled instance is discarded so that the new connection pool
(opened by the lifespan) is always used.  All queries reuse the same compiled
:class:`~langgraph.graph.state.CompiledStateGraph` for the lifetime of the
process — eliminating the per-query graph rebuild (~5–20 ms) and cold
PostgreSQL connection (~10–50 ms) that occurred when
``build_unified_graph().compile()`` was called inside ``run_graph_async``.

Thread safety
-------------
``CompiledStateGraph.ainvoke`` is thread-safe for concurrent queries because
thread isolation is enforced via ``config["configurable"]["thread_id"]`` passed
at invocation time.  The pooled checkpointer acquires a connection from the pool
per checkpoint operation and returns it immediately — no shared mutable state
between concurrent invocations.

Usage
-----
Call :func:`init_compiled_graph` once in the FastAPI lifespan (after
:func:`~backend.db.postgres.pool.open_pools`), then use
:func:`get_compiled_graph` everywhere::

    # In lifespan:
    await init_compiled_graph()

    # In runner.py:
    graph = get_compiled_graph()
    final_state = await graph.ainvoke(initial_state, config)
"""

from __future__ import annotations

import logging

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.state import CompiledStateGraph

from backend.db.postgres.pool import get_checkpointer_pool
from backend.graph.builder import build_unified_graph
from backend.graph.errors import GRAPH_NOT_INITIALIZED

logger = logging.getLogger(__name__)

_compiled_graph: CompiledStateGraph | None = None


async def init_compiled_graph() -> None:
    """Build, compile, and cache the unified graph with a pooled checkpointer.

    Must be called after :func:`~backend.db.postgres.pool.open_pools` so the
    checkpointer pool is already open.  Always discards any previous compiled
    graph and rebuilds fresh — ensures the new checkpointer pool (opened at
    each lifespan entry) is used and no stale state is carried over.
    """
    global _compiled_graph
    if _compiled_graph is not None:
        logger.info("[compiled] discarding previous compiled graph — rebuilding with fresh pool")
        _compiled_graph = None
    pool = get_checkpointer_pool()
    cp = AsyncPostgresSaver(pool)
    await cp.setup()
    _compiled_graph = build_unified_graph().compile(checkpointer=cp)
    logger.info("[compiled] unified graph compiled with pooled AsyncPostgresSaver")


def get_compiled_graph() -> CompiledStateGraph:
    """Return the pre-compiled graph.

    Returns:
        The singleton :class:`~langgraph.graph.state.CompiledStateGraph`.

    Raises:
        RuntimeError: If :func:`init_compiled_graph` has not been called.
    """
    if _compiled_graph is None:
        raise RuntimeError(
            f"[{GRAPH_NOT_INITIALIZED}] Compiled graph not initialised — call init_compiled_graph() in the FastAPI lifespan"
        )
    return _compiled_graph
