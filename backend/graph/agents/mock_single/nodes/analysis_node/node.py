"""node — LangGraph node function for the mock_single analysis stage.

Receives the ``merged_analysis`` JSON payload from ``merge_node`` and runs
the concurrency Celery stream path so the browser receives a rate-limited
token stream in real time.

Node position in the pipeline::

    (outer graph) mock_single_subgraph → mock_analysis → END

The ``mock_analysis`` node is wired DIRECTLY to the outer routing graph (not
inside the nested ``mock_single_subgraph``).

Design note — no ``interrupt()``
---------------------------------
An earlier design called ``interrupt()`` here so that a pause signal could be
honoured at this checkpoint boundary.  That design was abandoned because:

1. ``interrupt()`` inside an outer-graph StateGraph node causes
   ``Command(resume=True)`` to load an earlier checkpoint (before
   ``mock_single_subgraph`` ran), re-triggering the router and looping.
2. Pause is now handled by direct ``asyncio.Task.cancel()`` in
   ``pause_query`` (same as cancel), so no checkpoint boundary is needed.

``CancelledError`` from a direct cancel propagates naturally through
``_run_analysis_node`` → ``mock_analysis_node`` → the asyncio task wrapper.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from backend.graph.state import StreamRunState
from backend.graph.utils.execution_log import update_node_execution_status
from backend.graph.agents.mock_single.nodes.analysis_node.tasks import run_concurrency_task
from backend.sse_notifications.node import emit_node_input, emit_node_output, emit_node_status

logger = logging.getLogger(__name__)

_NODE_NAME: str = "mock_analysis"

# Concurrency stream parameters.
_TOKEN_PER_SEC: int = 500
_INGEST_TIMEOUT_SECS: int = 30


async def _run_analysis_node(
    thread_id: str,
    parent_node_execution_id: int | None,
) -> dict:
    """Execute the analysis node: DB tracking, Celery dispatch, emit events.

    All side effects (UUID generation, DB writes, SSE emits) live here so
    ``mock_analysis_node`` stays clean.  ``CancelledError`` is re-raised after
    emitting the cancelled status so the outer asyncio task wrapper handles it.

    Args:
        thread_id:              LangGraph thread UUID.
        parent_node_execution_id: node_execution_id from the preceding merge node.

    Returns:
        Partial state update with ``node_execution_id``, ``node_id``,
        ``task_id``, ``stream_id``, and ``result``.
    """
    node_id: str = str(uuid.uuid4())
    task_id: str = str(uuid.uuid4())
    stream_id: str = str(uuid.uuid4())
    run_id: str = str(uuid.uuid4())

    node_execution_id, t0 = await emit_node_input(
        thread_id,
        _NODE_NAME,
        {
            "token_per_sec": _TOKEN_PER_SEC,
            "timeout_secs": _INGEST_TIMEOUT_SECS,
            "node_id": node_id,
            "task_id": task_id,
            "stream_id": stream_id,
        },
        node_uuid=node_id,
        parent_node_execution_ids=[parent_node_execution_id] if parent_node_execution_id else [],
    )
    await emit_node_status(thread_id, node_id, _NODE_NAME, "running")

    terminal_status = "completed"
    try:
        task_result = await run_concurrency_task(
            thread_id=thread_id,
            token_per_sec=_TOKEN_PER_SEC,
            timeout_secs=_INGEST_TIMEOUT_SECS,
            node_execution_id=node_execution_id,
            t0_node=t0,
            node_id=node_id,
            task_id=task_id,
            stream_id=stream_id,
            run_id=run_id,
        )
    except asyncio.CancelledError:
        terminal_status = "cancelled"
        await update_node_execution_status(node_execution_id, terminal_status)
        await emit_node_status(thread_id, node_id, _NODE_NAME, terminal_status)
        raise
    except Exception:
        terminal_status = "failed"
        await update_node_execution_status(node_execution_id, terminal_status)
        await emit_node_status(thread_id, node_id, _NODE_NAME, terminal_status)
        raise

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    ended_at_ms = await emit_node_output(
        thread_id, _NODE_NAME, node_execution_id, {"result": task_result.result_str}, elapsed_ms,
    )
    await emit_node_status(thread_id, node_id, _NODE_NAME, terminal_status, ended_at_ms=ended_at_ms)

    logger.info(
        "[mock_analysis] completed thread_id=%s node_id=%s elapsed_ms=%d",
        thread_id, node_id, elapsed_ms,
    )
    return {
        "node_execution_id": node_execution_id,
        "node_id": node_id,
        "task_id": task_id,
        "stream_id": stream_id,
        "result": task_result.result_str,
    }


async def mock_analysis_node(state: StreamRunState) -> dict:
    """LangGraph node: run the analysis stream directly (no interrupt checkpoint).

    Wired to the OUTER graph (not inside ``mock_single_subgraph``).
    ``CancelledError`` from a direct ``pause_query`` / ``cancel_query`` cancel
    propagates naturally through this node to the outer asyncio task wrapper.

    Args:
        state: :class:`~backend.graph.state.StreamRunState` carrying
               ``merged_analysis`` and ``node_execution_id`` (merge node's exec ID).

    Returns:
        Partial state update with ``node_execution_id``, ``node_id``,
        ``task_id``, ``stream_id``, and ``result``.
    """
    thread_id: str = state["thread_id"]
    parent_node_execution_id: int | None = state.get("node_execution_id")
    symbol: str = (state.get("merged_analysis") or {}).get("symbol", "AAPL")

    logger.info(
        "[mock_analysis] symbol=%s token_per_sec=%d timeout_secs=%d thread_id=%s",
        symbol, _TOKEN_PER_SEC, _INGEST_TIMEOUT_SECS, thread_id,
    )

    return await _run_analysis_node(thread_id, parent_node_execution_id)


__all__ = ["mock_analysis_node"]
