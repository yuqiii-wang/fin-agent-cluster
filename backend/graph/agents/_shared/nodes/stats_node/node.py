"""node — thin LangGraph node function for the stats fetch stage.

Node position in the pipeline::

    query_node → [news_node, stats_node] → merge_node  ← fan-out / fan-in

Durable-execution design
------------------------
Side effects (UUID generation, DB tracking, task lifecycle) live inside the
``@task``-decorated :func:`_run_stats_node` so they are checkpointed when the
task completes.  On resume, a completed ``_run_stats_node`` is *replayed* from
the checkpoint — never re-executed — which eliminates the duplicate-node-id
fork seen in the UI.

NOTE: ``interrupt()`` is intentionally NOT used here.  See news_node/node.py
for the full rationale — parallel fan-out nodes sharing the same interrupt()
checkpoint cause sequential ``Command(resume=True)`` passes to re-execute
already-completed @tasks (different node_execution_ids per pass).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from langgraph.func import task

from backend.graph.agents._shared.nodes.stats_node.models import StatsNodeInput, StatsNodeOutput
from backend.graph.agents._shared.nodes.stats_node.tasks import run_fetch_stats_task
from backend.graph.state import StreamRunState
from backend.graph.utils.execution_log import update_node_execution_status
from backend.sse_notifications.node import emit_node_input, emit_node_output, emit_node_status

logger = logging.getLogger(__name__)

_NODE_NAME: str = "mock_stats"


@task
async def _run_stats_node(
    thread_id: str,
    parent_node_execution_id: int | None,
    symbol: str,
    period: str,
) -> dict:
    """All stats-node side effects: UUIDs, DB tracking, fetch, emit events.

    Wrapped in ``@task`` so the result is checkpointed on completion.
    On resume after a cancel, a completed task is replayed — never
    re-executed — keeping ``node_execution_id`` / ``node_id`` stable.
    """
    node_id: str = str(uuid.uuid4())
    task_id: str = str(uuid.uuid4())

    node_input = StatsNodeInput(symbol=symbol, period=period, node_id=node_id, task_id=task_id)
    node_execution_id, t0 = await emit_node_input(
        thread_id,
        _NODE_NAME,
        node_input.model_dump(),
        node_uuid=node_id,
        parent_node_execution_ids=[parent_node_execution_id] if parent_node_execution_id else [],
    )
    await emit_node_status(thread_id, node_id, _NODE_NAME, "running")

    try:
        records = await run_fetch_stats_task(
            thread_id, task_id, node_execution_id, node_id,
            symbol=symbol, period=period,
        )
    except asyncio.CancelledError:
        await update_node_execution_status(node_execution_id, "cancelled")
        await emit_node_status(thread_id, node_id, _NODE_NAME, "cancelled")
        raise
    except Exception:
        await update_node_execution_status(node_execution_id, "failed")
        await emit_node_status(thread_id, node_id, _NODE_NAME, "failed")
        raise

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    node_output = StatsNodeOutput(symbol=symbol, period=period, record_count=len(records))
    ended_at_ms = await emit_node_output(
        thread_id, _NODE_NAME, node_execution_id, node_output.model_dump(), elapsed_ms,
    )
    await emit_node_status(thread_id, node_id, _NODE_NAME, "completed", ended_at_ms=ended_at_ms)

    logger.info(
        "[mock_stats] fetched %d records symbol=%s period=%s thread_id=%s node_id=%s elapsed_ms=%d",
        len(records), symbol, period, thread_id, node_id, elapsed_ms,
    )
    return {"stats_node_execution_id": node_execution_id, "stats_records": records}


async def mock_stats_node(state: StreamRunState) -> dict:
    """LangGraph node: delegate directly to ``@task`` (no interrupt checkpoint).

    All DB writes / SSE emits are inside :func:`_run_stats_node`.
    ``interrupt()`` is intentionally absent — see module docstring for rationale.

    Args:
        state: :class:`~backend.graph.state.StreamRunState`.

    Returns:
        Partial state update with ``stats_node_execution_id`` and
        ``stats_records``.
    """
    thread_id: str = state["thread_id"]
    parent_node_execution_id: int | None = state.get("node_execution_id")
    query_response: dict = state.get("query_response") or {}
    symbol: str = query_response.get("symbol", "AAPL")
    period: str = query_response.get("parameters", {}).get("period", "1d")

    return await _run_stats_node(thread_id, parent_node_execution_id, symbol, period)


__all__ = ["mock_stats_node"]

