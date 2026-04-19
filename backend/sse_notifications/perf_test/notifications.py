"""Performance-test SSE notifications — throughput metrics emission.

Emits a ``perf_test_metrics`` SSE event via pg_notify after each completed
performance-test run so the frontend can display real-time throughput stats.

This is separate from the generic task lifecycle path because performance
metrics (tokens/sec, latency percentiles) are not stored in ``fin_agents.tasks``
and do not follow the standard started → completed lifecycle.
"""

from __future__ import annotations

import logging

from backend.sse_notifications.channel import pg_notify

logger = logging.getLogger(__name__)


async def emit_perf_test_metrics(
    thread_id: str,
    total_tokens: int,
    elapsed_ms: int,
    tokens_per_second: float,
    num_requests: int,
) -> None:
    """Emit a ``perf_test_metrics`` SSE event with throughput statistics.

    Fired by the perf-test graph node after the full token stream completes.
    Does not write to the database — metrics are ephemeral.

    Args:
        thread_id:         LangGraph thread UUID.
        total_tokens:      Number of tokens produced across all requests.
        elapsed_ms:        Wall-clock time in milliseconds for the whole test.
        tokens_per_second: Aggregate tokens per second throughput.
        num_requests:      Number of parallel mock-stream requests run.
    """
    await pg_notify(
        thread_id,
        {
            "event": "perf_test_metrics",
            "total_tokens": total_tokens,
            "elapsed_ms": elapsed_ms,
            "tokens_per_second": round(tokens_per_second, 2),
            "num_requests": num_requests,
        },
    )
    logger.info(
        "[perf_test] metrics emitted tps=%.1f tokens=%d elapsed_ms=%d thread_id=%s",
        tokens_per_second,
        total_tokens,
        elapsed_ms,
        thread_id,
    )


async def emit_perf_test_stopped(
    thread_id: str,
    duration_secs: int,
) -> None:
    """Emit a ``perf_test_stopped`` SSE event when the timeout fires.

    Signals the frontend to freeze the metrics panel and display final stats
    for all sessions.  Only emitted when the mock producer hit the deadline
    before finishing the full token budget.  Does not write to the database —
    this is an ephemeral control event.

    Args:
        thread_id:     LangGraph thread UUID.
        duration_secs: Configured test duration in seconds.
    """
    await pg_notify(
        thread_id,
        {
            "event": "perf_test_stopped",
            "duration_secs": duration_secs,
        },
    )
    logger.info(
        "[perf_test] stopped emitted duration_secs=%d thread_id=%s",
        duration_secs,
        thread_id,
    )


async def emit_perf_test_complete(
    thread_id: str,
    total_tokens: int,
    tps: float,
) -> None:
    """Emit a ``perf_test_complete`` SSE event when all requested tokens are streamed.

    Fired by the perf-test node when the mock producer finishes the full token
    budget before the timeout fires.  Signals the frontend to mark this specific
    session as completed in the grid immediately, without waiting for the
    terminal ``done`` event.  Does not write to the database — this is an
    ephemeral control event.

    Args:
        thread_id:    LangGraph thread UUID.
        total_tokens: Number of tokens published.
        tps:          Tokens per second throughput.
    """
    await pg_notify(
        thread_id,
        {
            "event": "perf_test_complete",
            "total_tokens": total_tokens,
            "tps": round(tps, 2),
        },
    )
    logger.info(
        "[perf_test] complete emitted total_tokens=%d tps=%.1f thread_id=%s",
        total_tokens,
        tps,
        thread_id,
    )


__all__ = ["emit_perf_test_metrics", "emit_perf_test_stopped", "emit_perf_test_complete"]
