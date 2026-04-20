"""Redis Streams token publisher.

Provides a shared connection-pool client and ``stream_token`` / ``delete_stream``
helpers for publishing LLM token payloads to per-thread Redis Streams (XADD).

Only **token** events travel through Redis Streams.  Task lifecycle events
(started, completed, failed, done) are delivered via PostgreSQL NOTIFY so they
carry authoritative data straight from the DB commit.
"""

from __future__ import annotations

import json
import logging
import asyncio
import threading
import time
from collections import defaultdict
from datetime import date, datetime
from typing import Any

import redis.asyncio as aioredis

from backend.config import get_settings

logger = logging.getLogger(__name__)

_publish_client: aioredis.Redis | None = None
_publish_client_loop_id: int | None = None

# Per-thread token aggregation: thread_id -> (count, t_last_log)
_token_stats: dict[str, tuple[int, float]] = defaultdict(lambda: (0, time.time()))

# Global XADD audit counter for the 5-min summary.
_xadd_count: int = 0
_xadd_last_flush: float = time.monotonic()
_xadd_lock = threading.Lock()
_SUMMARY_INTERVAL: float = 300.0  # 5 minutes

# Maximum number of token entries kept per stream key.
# Older entries are trimmed automatically by XADD MAXLEN ~ to avoid unbounded growth.
_STREAM_MAXLEN = 10_000


def stream_key(thread_id: str) -> str:
    """Return the Redis Stream key for token events of a given thread.

    Args:
        thread_id: LangGraph UUID thread identifier.

    Returns:
        Stream key, e.g. ``tokens:<uuid>``.
    """
    return f"tokens:{thread_id}"


async def _get_publish_client() -> aioredis.Redis:
    """Return (or lazily create) the shared publish Redis client.

    Recreated when the running event loop changes to avoid stale connection
    pools (e.g. Celery tasks each call ``asyncio.run()`` which closes the
    previous loop).

    Returns:
        A connected ``redis.asyncio.Redis`` instance backed by a connection pool.
    """
    global _publish_client, _publish_client_loop_id
    current_id = id(asyncio.get_running_loop())
    if _publish_client is not None and _publish_client_loop_id != current_id:
        try:
            await _publish_client.aclose()
        except Exception:  # noqa: BLE001
            pass
        _publish_client = None
        _publish_client_loop_id = None
    if _publish_client is None:
        settings = get_settings()
        _publish_client = aioredis.from_url(
            settings.DATABASE_REDIS_URL,
            decode_responses=True,
        )
        _publish_client_loop_id = current_id
    return _publish_client


def _default_json(obj: Any) -> str:
    """JSON serialiser fallback for datetime/date objects."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _track_xadd() -> None:
    """Increment the XADD counter and emit a 5-min summary when due.

    Thread-safe: uses ``_xadd_lock`` so it is safe to call from multiple
    asyncio event loops (e.g. several Celery worker threads running
    ``asyncio.run()`` concurrently).
    """
    global _xadd_count, _xadd_last_flush
    with _xadd_lock:
        _xadd_count += 1
        now = time.monotonic()
        if now - _xadd_last_flush >= _SUMMARY_INTERVAL:
            count = _xadd_count
            _xadd_count = 0
            _xadd_last_flush = now
            logger.info(
                "[Redis Streams 5-min summary]\n"
                "  tokens:* XADD (publisher/worker): %d writes",
                count,
            )


async def stream_token(thread_id: str, payload: dict) -> None:
    """Append a token event to the thread's Redis Stream.

    Uses ``XADD … MAXLEN ~ {_STREAM_MAXLEN}`` for automatic trimming so the
    stream does not grow without bound if the consumer is slow or absent.

    Args:
        thread_id: LangGraph thread ID that identifies the stream key.
        payload:   Token event dict — must include ``"event": "token"``.
    """
    try:
        client = await _get_publish_client()
        key = stream_key(thread_id)
        raw = json.dumps(payload, default=_default_json)
        await client.xadd(key, {"data": raw}, maxlen=_STREAM_MAXLEN, approximate=True)
        _track_xadd()

        count, t_last = _token_stats[thread_id]
        count += 1
        now = time.time()
        if now - t_last >= 10.0:
            elapsed = now - t_last
            tps = count / elapsed if elapsed > 0 else 0
            logger.debug(
                "[publisher.stream_token] token_summary tokens=%d tps=%.0f thread_id=%s",
                count, tps, thread_id,
            )
            _token_stats[thread_id] = (0, now)
        else:
            _token_stats[thread_id] = (count, t_last)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[publisher.stream_token] failed thread_id=%s: %s", thread_id, exc)


async def delete_stream(thread_id: str) -> None:
    """Delete the Redis Stream for *thread_id* after the query finishes.

    Called by ``emit_done`` so the stream key does not accumulate in Redis
    after the session ends.

    Args:
        thread_id: LangGraph thread ID.
    """
    _token_stats.pop(thread_id, None)
    try:
        client = await _get_publish_client()
        await client.delete(stream_key(thread_id))
        logger.debug("[publisher.delete_stream] deleted thread_id=%s", thread_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[publisher.delete_stream] failed thread_id=%s: %s", thread_id, exc)
