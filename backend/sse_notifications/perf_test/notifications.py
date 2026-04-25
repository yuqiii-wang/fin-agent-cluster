"""Performance-test SSE notifications — throughput metrics emission.

Emits perf-test events directly via Redis Pub/Sub after each phase transition
so the frontend can display real-time throughput stats.

This is separate from the generic task lifecycle path because performance
metrics (tokens/sec, latency percentiles) are not stored in ``fin_agents.tasks``
and do not follow the standard started → completed lifecycle.
"""

from __future__ import annotations

import logging

from backend.sse_notifications.channel import publish_lifecycle

logger = logging.getLogger(__name__)



async def emit_perf_test_stopped(
    thread_id: str,
    duration_secs: int,
    total_published: int = 0,
) -> None:
    """Emit a ``perf_test_stopped`` SSE event when the timeout fires.

    Signals the frontend to freeze the metrics panel and display final stats
    for all sessions.  Only emitted when the mock producer hit the deadline
    before finishing the full token budget.  Does not write to the database —
    this is an ephemeral control event.

    Args:
        thread_id:       LangGraph thread UUID.
        duration_secs:   Configured test duration in seconds.
        total_published: Actual tokens published to the SSE stream before the
                         timeout fired.  The frontend uses this to know the
                         real target — which may be less than the configured
                         token count when ingest hit the deadline early.
    """
    await publish_lifecycle(
        thread_id,
        {
            "event": "perf_test_stopped",
            "duration_secs": duration_secs,
            "total_published": total_published,
        },
    )
    logger.info(
        "[perf_test] stopped emitted duration_secs=%d total_published=%d thread_id=%s",
        duration_secs,
        total_published,
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
    await publish_lifecycle(
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
    await publish_lifecycle(
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


async def emit_perf_ingest_progress(
    thread_id: str,
    produced: int,
    total_tokens: int,
    elapsed_ms: int,
    ingest_tps: float,
    status: str,
) -> None:
    """Emit a ``perf_ingest_progress`` SSE event during the ingest phase.

    Fired approximately every second by :func:`~backend.graph.agents.perf_test.tasks.fanout_to_streams.run_ingest_first_half`
    and :func:`~backend.graph.agents.perf_test.tasks.fanout_to_streams.run_ingest_second_half`.
    Carries the running produced count and ingest TPS so the frontend can
    display a live progress bar.  Does not write to the database.

    Args:
        thread_id:    LangGraph thread UUID.
        produced:     Number of tokens written so far.
        total_tokens: Total token budget for the test run.
        elapsed_ms:   Wall-clock milliseconds elapsed since ingest started.
        ingest_tps:   Current ingest throughput in tokens per second.
        status:       ``"running"``, ``"half_done"``, ``"completed"``, or ``"timeout"``.
    """
    await publish_lifecycle(
        thread_id,
        {
            "event": "perf_ingest_progress",
            "produced": produced,
            "total_tokens": total_tokens,
            "elapsed_ms": elapsed_ms,
            "ingest_tps": round(ingest_tps),
            "status": status,
        },
    )


__all__ = [
    "emit_perf_test_stopped",
    "emit_perf_test_complete",
    "emit_perf_ingest_complete",
    "emit_perf_ingest_progress",
]
