"""stats_node — mock market-stats fetching LangGraph node.

Reads the ``query_response`` from state (produced by ``mock_query_node``) and
calls the :class:`~backend.resources.stats.client.StatsClient` to retrieve mock
market statistics.  In production this would call a live market-data feed.

Node position in the pipeline:

    query_node → [news_node, stats_node] → merge_node  ← fan-out / fan-in

Refactored to use:
- ``@task`` from ``langgraph.func`` for the fetch computation so LangGraph
  checkpoints the result and avoids re-execution on resume.
- ``interrupt()`` from ``langgraph.types`` as the step-approval checkpoint,
  replacing the former ``check_node_cancel`` Redis signal.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone

from langgraph.func import task
from langgraph.types import interrupt

from backend.graph.agents.mock_perf.errors import STATS_FAILED
from backend.graph.state import StreamRunState
from backend.graph.utils.execution_log import (
    finish_node_execution,
    start_node_execution,
    update_node_execution_status,
)
from backend.resources.stats import StatsClient
from backend.sse_notifications import (
    TaskCancelledSignal,
    cancel_task,
    complete_task,
    create_task,
    fail_task,
)
from backend.sse_notifications.node import emit_node_status

logger = logging.getLogger(__name__)

_NODE_NAME: str = "mock_stats"


@task
async def _fetch_stats_task(
    thread_id: str,
    task_id: str,
    node_execution_id: int,
    node_id: str,
    symbol: str,
    period: str,
) -> list[dict]:
    """LangGraph ``@task``: fetch market stats and emit task lifecycle events.

    Result is checkpointed — not re-executed on resume after a cancel/crash.

    Args:
        thread_id:         LangGraph thread UUID.
        task_id:           Task primary-key UUID.
        node_execution_id: FK to the parent ``node_executions`` row.
        node_id:           Node-level UUID for SSE events.
        symbol:            Ticker symbol to fetch stats for.
        period:            Time period for OHLCV data (e.g. ``"1d"``).

    Returns:
        List of serialised :class:`~backend.resources.stats.models.StatsRecord`
        dicts.
    """
    await create_task(
        thread_id,
        "MOCK_STATS",
        node_execution_id,
        provider="mock",
        task_id=task_id,
        extra_payload={"node_id": node_id, "symbol": symbol, "period": period},
    )

    try:
        client = StatsClient()
        response = await client.list_stats(symbol=symbol, period=period)
        records = [r.model_dump(mode="json") for r in response.items]
        if hasattr(client, "aclose"):
            await client.aclose()
    except (asyncio.CancelledError, TaskCancelledSignal):
        await cancel_task(thread_id, task_id, "MOCK_STATS")
        await update_node_execution_status(node_execution_id, "cancelled")
        await emit_node_status(thread_id, node_id, _NODE_NAME, "cancelled")
        raise asyncio.CancelledError()
    except Exception as exc:
        logger.exception("[mock_stats] fetch error thread_id=%s: %s", thread_id, exc)
        await fail_task(thread_id, task_id, "MOCK_STATS", str(exc), error_code=STATS_FAILED)
        await emit_node_status(thread_id, node_id, _NODE_NAME, "failed")
        raise

    await complete_task(
        thread_id,
        task_id,
        "MOCK_STATS",
        output={"symbol": symbol, "period": period, "record_count": len(records)},
    )
    return records


async def mock_stats_node(state: StreamRunState) -> dict:
    """Fetch mock market-statistics records for the symbol from ``query_response``.

    Uses ``interrupt()`` as a step-approval checkpoint (replacing the former
    ``check_node_cancel`` Redis signal) then delegates the fetch to the
    ``@task``-decorated :func:`_fetch_stats_task`.

    Args:
        state: :class:`~backend.graph.state.StreamRunState`.

    Returns:
        Partial state update with ``stats_records`` (list of serialised
        :class:`~backend.resources.stats.models.StatsRecord` dicts).
    """
    thread_id: str = state["thread_id"]
    parent_node_execution_id: int | None = state.get("node_execution_id")
    query_response: dict = state.get("query_response") or {}
    symbol: str = query_response.get("symbol", "AAPL")
    period: str = query_response.get("parameters", {}).get("period", "1d")

    # ── Step-approval interrupt (replaces check_node_cancel) ──────────────
    interrupt({"action": "step_approval", "node": _NODE_NAME, "thread_id": thread_id})

    node_id: str = str(uuid.uuid4())
    task_id: str = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()

    node_execution_id = await start_node_execution(
        thread_id,
        _NODE_NAME,
        {"symbol": symbol, "period": period, "node_id": node_id, "task_id": task_id},
        started_at,
        node_uuid=node_id,
        parent_node_execution_id=parent_node_execution_id,
    )
    await emit_node_status(thread_id, node_id, _NODE_NAME, "running")

    try:
        records = await _fetch_stats_task(thread_id, task_id, node_execution_id, node_id, symbol, period)
    except asyncio.CancelledError:
        await update_node_execution_status(node_execution_id, "cancelled")
        await emit_node_status(thread_id, node_id, _NODE_NAME, "cancelled")
        raise
    except Exception:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        await finish_node_execution(node_execution_id, {}, elapsed_ms, status="failed")
        await emit_node_status(thread_id, node_id, _NODE_NAME, "failed")
        raise

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    await finish_node_execution(
        node_execution_id,
        {"symbol": symbol, "period": period, "record_count": len(records)},
        elapsed_ms,
    )
    await emit_node_status(thread_id, node_id, _NODE_NAME, "completed")

    logger.info(
        "[mock_stats] fetched %d records symbol=%s period=%s thread_id=%s node_id=%s elapsed_ms=%d",
        len(records), symbol, period, thread_id, node_id, elapsed_ms,
    )
    return {"node_execution_id": node_execution_id, "stats_records": records}


__all__ = ["mock_stats_node"]
