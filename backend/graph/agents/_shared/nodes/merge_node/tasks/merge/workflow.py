"""workflow — async task function for the merge aggregation stage.

Encapsulates the full task lifecycle (``create_task`` → merge → ``complete_task``)
so :func:`~backend.graph.agents._shared.nodes.merge_node.node.merge_node` stays
a thin orchestrator.

Merge strategy
--------------
Top-level metadata fields (``symbol``, ``analysis_type``, ``time_horizon``) from
the upstream ``query_response`` are promoted to the root of the output dict.
News articles and stats records are stored under their respective keys.
"""

from __future__ import annotations

import asyncio
import logging

from langgraph.func import task

from backend.graph.agents._shared.errors import MERGE_FAILED
from backend.graph.agents._shared.nodes.merge_node.tasks.merge.models import MergeTaskOutput
from backend.sse_notifications import (
    TaskCancelledSignal,
    cancel_task,
    complete_task,
    create_task,
    fail_task,
)

logger = logging.getLogger(__name__)


@task
async def run_merge_task(
    thread_id: str,
    task_id: str,
    node_execution_id: int,
    node_id: str,
    *,
    news_json: list[dict],
    stats_json: list[dict],
    meta: dict,
) -> MergeTaskOutput:
    """Merge news + stats into one combined :class:`MergeTaskOutput`.

    Creates a DB task row (``"MERGE"`` key), performs the merge, then marks it
    completed.  Raises on cancel / error so the caller
    (:func:`~backend.graph.agents._shared.nodes.merge_node.node.merge_node`)
    can handle node-level teardown.

    Args:
        thread_id:         LangGraph thread UUID.
        task_id:           Pre-generated task UUID passed as ``extra_payload``.
        node_execution_id: FK to the parent ``node_executions`` row.
        node_id:           Node governance UUID (passed to extra_payload).
        news_json:         List of news-article dicts from ``news_node``.
        stats_json:        List of market-stats record dicts from ``stats_node``.
        meta:              Top-level metadata dict — must contain at least
                           ``symbol``, ``analysis_type``, ``time_horizon``.

    Returns:
        :class:`~backend.graph.agents._shared.nodes.merge_node.tasks.merge.models.MergeTaskOutput`
        ready to be stored in graph state as ``merged_analysis``.

    Raises:
        asyncio.CancelledError: Propagated from cancel / TaskCancelledSignal.
        Exception:              Any unexpected merge failure.
    """
    symbol: str = meta.get("symbol", "AAPL")

    await asyncio.sleep(0)  # yield to event loop before task creation

    await create_task(
        thread_id,
        "MERGE",
        node_execution_id,
        provider="mock",
        task_id=task_id,
        extra_payload={
            "node_id": node_id,
            "symbol": symbol,
            "input": {
                "news_count": len(news_json),
                "stats_count": len(stats_json),
            },
        },
    )

    try:
        output = MergeTaskOutput(
            symbol=symbol,
            analysis_type=meta.get("analysis_type", "comprehensive"),
            time_horizon=meta.get("time_horizon", "1w"),
            news=news_json,
            stats=stats_json,
        )
    except (asyncio.CancelledError, TaskCancelledSignal):
        await cancel_task(thread_id, task_id, "MERGE")
        raise asyncio.CancelledError()
    except Exception as exc:
        logger.exception(
            "[merge_task] merge failed symbol=%s thread_id=%s: %s",
            symbol, thread_id, exc,
        )
        await fail_task(thread_id, task_id, "MERGE", str(exc), error_code=MERGE_FAILED)
        raise

    await complete_task(
        thread_id,
        task_id,
        "MERGE",
        output={
            "symbol": symbol,
            "merged_keys": list(output.as_dict().keys()),
            "news_count": len(news_json),
            "stats_count": len(stats_json),
        },
    )

    logger.debug(
        "[merge_task] completed symbol=%s news=%d stats=%d thread_id=%s",
        symbol, len(news_json), len(stats_json), thread_id,
    )
    return output


__all__ = ["run_merge_task"]
