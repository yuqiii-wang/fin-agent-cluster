"""Redis-backed stable signal for concurrent perf-test sessions.

The frontend sends a ``POST /api/v1/users/query/{thread_id}/perf-stable``
request when it detects stable TPS.  This module exposes helpers to set and
check the signal so the running
:func:`~backend.streaming.workers.stream_ingest._ingest_concurrent`
Celery worker loop can react without polling the HTTP layer.

Key schema
----------
``fin:perf:stable:{stream_id}``
    Set to ``"1"`` by the API endpoint; polled and consumed by the ingest
    loop.  Keyed by ``stream_id`` (leaf-level Celery ingest run UUID) so
    concurrent streams on the same thread never cross-pollinate signals.
    Automatically expires after ``_STABLE_TTL`` seconds so a missed
    signal never blocks a future run.

    Shard routing uses ``stream_id`` — consistent with the key namespace.
"""

from __future__ import annotations

import logging

from backend.db.redis.router import get_redis_router

logger = logging.getLogger(__name__)

_STABLE_PREFIX: str = "fin:perf:stable:"
_STABLE_TTL: int = 120  # seconds — auto-expire if never consumed


async def set_perf_stable(stream_id: str, thread_id: str) -> None:
    """Signal that the concurrency perf stream identified by *stream_id* has reached stable TPS.

    Called by the ``POST /perf-stable`` API endpoint.  The running ingest
    loop polls :func:`check_and_consume_perf_stable` and stops gracefully
    when the flag is found.

    Args:
        stream_id: Celery ingest run UUID (key + shard routing).
        thread_id: LangGraph thread UUID (logged for correlation only).
    """
    client = get_redis_router().get_client_for_stream(stream_id)
    key = f"{_STABLE_PREFIX}{stream_id}"
    await client.setex(key, _STABLE_TTL, "1")
    logger.info("[perf_stable] flag set stream_id=%s thread_id=%s", stream_id, thread_id)


async def check_and_consume_perf_stable(stream_id: str, thread_id: str) -> bool:
    """Return True and delete the flag if the stable signal is present.

    Atomically checks and removes the flag so the ingest loop only reacts
    once even if polled multiple times during the same tick.

    Args:
        stream_id: Celery ingest run UUID (key + shard routing).
        thread_id: LangGraph thread UUID (retained for signature compatibility).

    Returns:
        ``True`` if the signal was present (and has now been consumed).
    """
    client = get_redis_router().get_client_for_stream(stream_id)
    key = f"{_STABLE_PREFIX}{stream_id}"
    deleted = await client.delete(key)
    return bool(deleted)


__all__ = [
    "set_perf_stable",
    "check_and_consume_perf_stable",
]
