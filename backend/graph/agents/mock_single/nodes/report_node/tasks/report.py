"""report — run_mock_report_task: silent-by-default token streaming for mock_single report stage.

Behaviour
---------
Generates mock "report" tokens at ``_TOKEN_PER_SEC`` rate for up to
``_TIMEOUT_SECS`` seconds.  Tokens are buffered in Redis by default and
are **not** pushed to Centrifugo unless the user opts in via::

    POST /api/v1/users/{thread_id}/tasks/{task_id}/enable-stream

Output has report-specific semantics: title, recommendation (BUY/HOLD/SELL),
and confidence score.

Task name: ``MOCK_REPORT_PREVIEW`` (see :mod:`backend.graph.agents.task_names`).
"""

from __future__ import annotations

import asyncio
import logging
import time

from backend.db.redis.session.task_preview import (
    cleanup_task_preview,
    is_task_stream_live,
    store_preview_token,
)
from backend.db.redis.streams.publisher import stream_token
from backend.graph.agents.mock_single.nodes.report_node.tasks.result import MockReportResult
from backend.graph.agents.task_names import MOCK_REPORT_PREVIEW
from backend.graph.utils.execution_log import finish_node_execution
from backend.sse_notifications import (
    TaskCancelledSignal,
    cancel_task,
    complete_task,
    create_task,
)
from backend.sse_notifications.task import fail_task

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_BATCH_SIZE: int = 15          # tokens published per batch iteration
_TOKEN_PER_SEC: int = 30       # target generation rate (slower than analysis)
_TIMEOUT_SECS: int = 10        # hard deadline

_REPORT_TITLE: str = "Mock Trading Signal Report"
_RECOMMENDATION: str = "BUY"
_CONFIDENCE: int = 78

# Pre-built vocabulary for mock "report" output.
_VOCAB: list[str] = [
    "## Executive Summary\n", "Based ", "on ", "technical ", "and ", "fundamental ",
    "analysis, ", "we ", "recommend ", "a ", "**BUY** ", "position. ",
    "## Signal Breakdown\n", "- RSI: ", "oversold ", "recovery ", "pattern. ",
    "- MACD: ", "bullish ", "crossover ", "confirmed. ",
    "- Volume: ", "above ", "30-day ", "average. ",
    "## Price Targets\n", "Entry: ", "$174 ", "Target: ", "$192 ",
    "Stop-loss: ", "$168. ",
    "## Risk Assessment\n", "Medium ", "risk. ", "Sector ", "momentum ",
    "supports ", "the ", "thesis. ",
]
_VOCAB_LEN: int = len(_VOCAB)

logger = logging.getLogger(__name__)


async def run_mock_report_task(
    thread_id: str,
    task_id: str,
    node_execution_id: int,
    node_id: str = "",
    t0_node: float | None = None,
) -> MockReportResult:
    """Simulate a trading signal report with opt-in token streaming.

    Generates mock report tokens at ``_TOKEN_PER_SEC`` tokens/second, buffering
    them in Redis.  Tokens are only forwarded to Centrifugo when the user has
    opted in by calling the enable-stream API endpoint.

    Args:
        thread_id:          LangGraph thread UUID.
        task_id:            Task invocation UUID.
        node_execution_id:  DB row ID from :func:`start_node_execution`.
        node_id:            Governance UUID of the parent node (used as extra_payload
                            so the frontend can match this task to its node circle).
        t0_node:            ``time.monotonic()`` captured at node entry.

    Returns:
        :class:`MockReportResult` with produced count, recommendation, and summary.

    Raises:
        asyncio.CancelledError: When the task is cancelled.
        Exception:              On unexpected failure.
    """
    if t0_node is None:
        t0_node = time.monotonic()

    pub_task_id = await create_task(
        thread_id,
        MOCK_REPORT_PREVIEW,
        node_execution_id,
        provider="mock",
        task_id=task_id,
        extra_payload={"node_id": node_id},
    )

    batch_delay = _BATCH_SIZE / _TOKEN_PER_SEC  # seconds per batch
    deadline = t0_node + _TIMEOUT_SECS
    produced = 0

    try:
        while time.monotonic() < deadline:
            batch_start = time.monotonic()

            # Generate one batch of tokens
            batch = [_VOCAB[(produced + i) % _VOCAB_LEN] for i in range(_BATCH_SIZE)]

            # Buffer every token in Redis
            for tok in batch:
                await store_preview_token(thread_id, task_id, tok)

            # If user opted in, publish to Centrifugo
            if await is_task_stream_live(thread_id, task_id):
                for tok in batch:
                    await stream_token(
                        thread_id,
                        {"event": "token", "task_id": task_id, "data": tok},
                    )

            produced += _BATCH_SIZE

            # Honour cancellation between batches
            elapsed_batch = time.monotonic() - batch_start
            sleep_time = max(batch_delay - elapsed_batch, 0)
            await asyncio.sleep(sleep_time)

    except (asyncio.CancelledError, TaskCancelledSignal):
        elapsed_ms = int((time.monotonic() - t0_node) * 1000)
        await cancel_task(thread_id, pub_task_id, MOCK_REPORT_PREVIEW)
        await finish_node_execution(node_execution_id, {"cancelled": True}, elapsed_ms)
        await cleanup_task_preview(thread_id, task_id)
        raise asyncio.CancelledError()
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - t0_node) * 1000)
        logger.exception(
            "[mock_report_task] error task_id=%s thread_id=%s: %s",
            task_id, thread_id, exc,
        )
        await fail_task(thread_id, pub_task_id, MOCK_REPORT_PREVIEW, str(exc))
        await finish_node_execution(node_execution_id, {"error": str(exc)[:500]}, elapsed_ms)
        await cleanup_task_preview(thread_id, task_id)
        raise

    total_elapsed_ms = int((time.monotonic() - t0_node) * 1000)
    result = MockReportResult(
        pub_task_id=pub_task_id,
        task_id=task_id,
        produced=produced,
        title=_REPORT_TITLE,
        recommendation=_RECOMMENDATION,
        confidence=_CONFIDENCE,
        result_str=(
            f"Report complete. Recommendation: {_RECOMMENDATION} "
            f"(confidence {_CONFIDENCE}%). Generated {produced} tokens "
            f"in {total_elapsed_ms}ms (opt-in streaming, {_TOKEN_PER_SEC} tok/s)."
        ),
    )
    await complete_task(
        thread_id,
        pub_task_id,
        MOCK_REPORT_PREVIEW,
        {
            "title": _REPORT_TITLE,
            "recommendation": _RECOMMENDATION,
            "confidence": _CONFIDENCE,
            "total_generated": produced,
            "elapsed_ms": total_elapsed_ms,
        },
    )
    await finish_node_execution(node_execution_id, result.as_node_output(), total_elapsed_ms)
    await cleanup_task_preview(thread_id, task_id)

    logger.info(
        "[mock_report_task] done recommendation=%s confidence=%d produced=%d elapsed_ms=%d task_id=%s thread_id=%s",
        _RECOMMENDATION, _CONFIDENCE, produced, total_elapsed_ms, task_id, thread_id,
    )
    return result


__all__ = ["run_mock_report_task"]
