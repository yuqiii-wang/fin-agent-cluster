"""analysis — run_mock_analysis_task: silent-by-default token streaming for mock_single.

Behaviour
---------
Generates mock "analysis" tokens at ``_TOKEN_PER_SEC`` rate for up to
``_TIMEOUT_SECS`` seconds.  Tokens are buffered in Redis by default and
are **not** pushed to Centrifugo unless the user opts in via::

    POST /api/v1/users/{thread_id}/tasks/{task_id}/enable-stream

This allows the graph node to complete its lifecycle and store a meaningful
result without flooding the frontend with tokens the user did not request.
When the user clicks the task in the graph inspector, the buffered tokens
are flushed and live streaming begins.

Task name: ``MOCK_ANALYSIS_PREVIEW`` (see :mod:`backend.graph.agents.task_names`).
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
from backend.graph.agents.mock_single.nodes.analysis_node.tasks.result import MockAnalysisResult
from backend.graph.agents.task_names import MOCK_ANALYSIS_PREVIEW
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

_BATCH_SIZE: int = 20          # tokens published per batch iteration
_TOKEN_PER_SEC: int = 50       # target generation rate
_TIMEOUT_SECS: int = 15        # hard deadline

# Pre-built vocabulary for mock "financial analysis" output.
_VOCAB: list[str] = [
    "The ", "market ", "shows ", "strong ", "bullish ", "momentum ", "with ",
    "RSI ", "at ", "72 ", "and ", "MACD ", "crossing ", "above ", "signal ",
    "line. ", "Volume ", "confirms ", "the ", "breakout. ", "Support ",
    "holds ", "at ", "key ", "Fibonacci ", "level. ", "Resistance ",
    "target: ", "$185 ", "— ", "entry ", "above ", "$176. ",
]
_VOCAB_LEN: int = len(_VOCAB)

logger = logging.getLogger(__name__)


async def run_mock_analysis_task(
    thread_id: str,
    task_id: str,
    node_execution_id: int,
    node_id: str = "",
    t0_node: float | None = None,
) -> MockAnalysisResult:
    """Simulate a financial analysis pass with opt-in token streaming.

    Generates mock tokens at ``_TOKEN_PER_SEC`` tokens/second, buffering them
    in Redis.  Tokens are only forwarded to Centrifugo when the user has opted
    in by calling the enable-stream API endpoint.

    Args:
        thread_id:          LangGraph thread UUID.
        task_id:            Task invocation UUID (matches the ``fin_agents.tasks`` row).
        node_execution_id:  DB row ID from :func:`start_node_execution`.
        node_id:            Governance UUID of the parent node (used as extra_payload
                            so the frontend can match this task to its node circle).
        t0_node:            ``time.monotonic()`` captured at node entry.

    Returns:
        :class:`MockAnalysisResult` with produced count and summary.

    Raises:
        asyncio.CancelledError: When the task is cancelled (already cleaned up).
        Exception:              On unexpected failure (already cleaned up).
    """
    if t0_node is None:
        t0_node = time.monotonic()

    pub_task_id = await create_task(
        thread_id,
        MOCK_ANALYSIS_PREVIEW,
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

            # If user opted in, publish to Centrifugo (one call per token to match
            # the live-streaming UX — the ``token`` event carries one chunk each).
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
        await cancel_task(thread_id, pub_task_id, MOCK_ANALYSIS_PREVIEW)
        await finish_node_execution(node_execution_id, {"cancelled": True}, elapsed_ms)
        await cleanup_task_preview(thread_id, task_id)
        raise asyncio.CancelledError()
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - t0_node) * 1000)
        logger.exception(
            "[mock_analysis_task] error task_id=%s thread_id=%s: %s",
            task_id, thread_id, exc,
        )
        await fail_task(thread_id, pub_task_id, MOCK_ANALYSIS_PREVIEW, str(exc))
        await finish_node_execution(node_execution_id, {"error": str(exc)[:500]}, elapsed_ms)
        await cleanup_task_preview(thread_id, task_id)
        raise

    total_elapsed_ms = int((time.monotonic() - t0_node) * 1000)
    result = MockAnalysisResult(
        pub_task_id=pub_task_id,
        task_id=task_id,
        produced=produced,
        result_str=(
            f"Analysis complete. Generated {produced} tokens "
            f"in {total_elapsed_ms}ms (opt-in streaming, {_TOKEN_PER_SEC} tok/s)."
        ),
    )
    await complete_task(
        thread_id,
        pub_task_id,
        MOCK_ANALYSIS_PREVIEW,
        {"total_generated": produced, "elapsed_ms": total_elapsed_ms},
    )
    await finish_node_execution(node_execution_id, result.as_node_output(), total_elapsed_ms)
    await cleanup_task_preview(thread_id, task_id)

    logger.info(
        "[mock_analysis_task] done produced=%d elapsed_ms=%d task_id=%s thread_id=%s",
        produced, total_elapsed_ms, task_id, thread_id,
    )
    return result


__all__ = ["run_mock_analysis_task"]
