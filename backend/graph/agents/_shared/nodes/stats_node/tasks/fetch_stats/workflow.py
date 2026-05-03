"""workflow — async task function for the mock stats fetch stage.

Encapsulates the full task lifecycle (``create_task`` → fetch → ``complete_task``)
so :func:`~backend.graph.agents._shared.nodes.stats_node.node.mock_stats_node`
stays a thin orchestrator.
"""

from __future__ import annotations

import asyncio
import logging

from langgraph.func import task

from backend.graph.agents._shared.errors import STATS_FAILED
from backend.resources.stats import StatsClient
from backend.sse_notifications import (
    TaskCancelledSignal,
    cancel_task,
    complete_task,
    create_task,
    fail_task,
)

logger = logging.getLogger(__name__)

_TASK_NAME: str = "MOCK_STATS"


@task
async def run_fetch_stats_task(
    thread_id: str,
    task_id: str,
    node_execution_id: int,
    node_id: str,
    *,
    symbol: str,
    period: str,
) -> list[dict]:
    """Fetch mock market-stats records and manage full task lifecycle.

    LangGraph ``@task``: result is checkpointed — not re-executed on resume.

    Creates a DB task row, calls :class:`~backend.resources.stats.client.StatsClient`,
    then marks the task completed.  Raises on cancel / error so the caller
    (:func:`~backend.graph.agents._shared.nodes.stats_node.node.mock_stats_node`)
    can handle node-level teardown.

    Args:
        thread_id:         LangGraph thread UUID.
        task_id:           Pre-generated task UUID.
        node_execution_id: FK to the parent ``node_executions`` row.
        node_id:           Node governance UUID.
        symbol:            Ticker symbol to fetch stats for.
        period:            Time period for the stats query (e.g. ``"1d"``).

    Returns:
        List of serialised :class:`~backend.resources.stats.models.StatsRecord` dicts.

    Raises:
        asyncio.CancelledError: When the task is cancelled (already cleaned up).
        Exception:              On fetch failure (already cleaned up).
    """
    await create_task(
        thread_id,
        _TASK_NAME,
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
        await cancel_task(thread_id, task_id, _TASK_NAME)
        raise asyncio.CancelledError()
    except Exception as exc:
        logger.exception("[fetch_stats] error thread_id=%s: %s", thread_id, exc)
        await fail_task(thread_id, task_id, _TASK_NAME, str(exc), error_code=STATS_FAILED)
        raise

    await complete_task(
        thread_id,
        task_id,
        _TASK_NAME,
        output={"symbol": symbol, "period": period, "record_count": len(records)},
    )
    return records


__all__ = ["run_fetch_stats_task"]
