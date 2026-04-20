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


async def emit_perf_ingest_complete(
    thread_id: str,
    ingest_ms: int,
    produced: int,
    stop_reason: str,
) -> None:
    """Emit a ``perf_ingest_complete`` SSE event when the ingest phase finishes.

    Fired by the perf-test node immediately after the ingest task completes
    (Phase 1 done, before Phase 2 pub starts).  Carries the authoritative
    backend ingest duration so the frontend can display an accurate "Ingest
    Time" column without relying on client-side timestamps.  Does not write
    to the database — this is an ephemeral control event.

    Args:
        thread_id:   LangGraph thread UUID.
        ingest_ms:   Wall-clock milliseconds for the ingest phase.
        produced:    Number of tokens written to the Redis perf stream.
        stop_reason: ``"completed"`` or ``"timeout"``.
    """
    await pg_notify(
        thread_id,
        {
            "event": "perf_ingest_complete",
            "ingest_ms": ingest_ms,
            "produced": produced,
            "stop_reason": stop_reason,
        },
    )
    logger.info(
        "[perf_test] ingest_complete emitted ingest_ms=%d produced=%d "
        "stop_reason=%s thread_id=%s",
        ingest_ms,
        produced,
        stop_reason,
        thread_id,
    )


async def emit_locust_complete(
    thread_id: str,
    consumed: int,
    tps: float,
    digest_ms: int,
) -> None:
    """Emit a ``locust_complete`` SSE event when the locust digest phase finishes.

    Fired by :func:`~backend.graph.agents.perf_test.tasks.locust_digest.run_locust_digest`
    after all tokens in the perf stream have been consumed.  This is the single
    aggregate event that the frontend grid uses to update session stats when
    ``pub_mode == "locust"`` — no per-token events are emitted in this mode.

    Args:
        thread_id:  LangGraph thread UUID.
        consumed:   Number of tokens read from the Redis perf stream.
        tps:        Digest throughput in tokens per second.
        digest_ms:  Wall-clock milliseconds for the digest phase.
    """
    await pg_notify(
        thread_id,
        {
            "event": "locust_complete",
            "consumed": consumed,
            "tps": round(tps, 2),
            "digest_ms": digest_ms,
        },
    )
    logger.info(
        "[perf_test] locust_complete emitted consumed=%d tps=%.1f "
        "digest_ms=%d thread_id=%s",
        consumed, tps, digest_ms, thread_id,
    )


async def emit_query_status(thread_id: str, phase: str) -> None:
    """Emit a ``query_status`` SSE event signalling a backend phase transition.

    Fires via pg_notify so the frontend grid can update the status column in
    real time.  The phase is also stored in Redis by the caller so
    late-connecting SSE clients recover the current phase via
    :func:`~backend.api.stream._replay_existing`.

    Phase progression:
        ``received`` → ``preparing`` → ``ingesting`` → ``sending``

    Args:
        thread_id: LangGraph thread UUID.
        phase:     One of ``"received"``, ``"preparing"``, ``"ingesting"``,
                   ``"sending"``.
    """
    await pg_notify(thread_id, {"event": "query_status", "phase": phase})
    logger.info(
        "[query_status] emitted phase=%s thread_id=%s",
        phase,
        thread_id,
    )


__all__ = [
    "emit_query_status",
    "emit_perf_test_metrics",
    "emit_perf_test_stopped",
    "emit_perf_test_complete",
    "emit_perf_ingest_complete",
    "emit_locust_complete",
]
