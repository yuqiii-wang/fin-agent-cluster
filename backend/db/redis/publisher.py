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
import dataclasses
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timezone
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


# ---------------------------------------------------------------------------
# Pending pg_notify store — ack-based delivery guarantee
# ---------------------------------------------------------------------------

#: Redis hash prefix for the pending-notify ack store.
_PENDING_PREFIX = "notify_pending:"
#: Maximum number of re-emit attempts before an entry is abandoned.
_MAX_RETRIES: int = 10
#: Per-retry delay in seconds (indexed by retry_count before the retry fires).
#: First two retries are fast (1 s, 2 s) for transient pg_notify hiccups;
#: subsequent retries grow exponentially up to a 300 s cap.
_RETRY_DELAYS_SECS: tuple[float, ...] = (
    1.0,    # initial wait  → first  retry at t+1 s
    2.0,    # after retry 1 → second retry at t+2 s
    4.0,    # after retry 2
    8.0,    # after retry 3
    16.0,   # after retry 4
    30.0,   # after retry 5
    60.0,   # after retry 6
    120.0,  # after retry 7
    300.0,  # after retry 8
    300.0,  # after retry 9  → retry 10 (final)
)
#: Redis hash TTL — covers the full retry schedule with headroom.
_PENDING_TTL_SECS: int = int(sum(_RETRY_DELAYS_SECS)) + 300  # ~1141 s


@dataclasses.dataclass(frozen=True)
class DrainEntry:
    """A single unacked pg_notify entry recovered from the pending hash.

    Attributes:
        field:       Hash field key (``"{event_type}:{task_id}"``).
        raw:         JSON-encoded SSE payload (ready to re-enqueue).
        event_type:  SSE event name, e.g. ``"completed"``.
        task_id:     DB task PK, or ``None`` for session-level events.
        retry_count: Retry number that is about to be emitted (1-based;
                     the envelope's ``retry_count`` was incremented before
                     this entry was returned).
        expired:     ``True`` when ``retry_count`` reached :data:`_MAX_RETRIES`
                     and the entry was deleted from the hash without re-emitting.
    """

    field: str
    raw: str
    event_type: str
    task_id: int | None
    retry_count: int
    expired: bool


def _pending_key(thread_id: str) -> str:
    """Return the Redis hash key for the pending-notify store of *thread_id*.

    Args:
        thread_id: LangGraph UUID.

    Returns:
        Key string, e.g. ``"notify_pending:<uuid>"``.
    """
    return f"{_PENDING_PREFIX}{thread_id}"


def _pending_field(event_type: str, task_id: int | None) -> str:
    """Build a deterministic hash field from event type and optional task_id.

    Args:
        event_type: SSE event name, e.g. ``"completed"``, ``"done"``.
        task_id:    DB task primary key, or ``None`` for session-level events.

    Returns:
        Field string, e.g. ``"completed:42"`` or ``"done:0"``.
    """
    return f"{event_type}:{task_id or 0}"


async def push_pending_notify(thread_id: str, event_type: str, task_id: int | None, raw: str) -> None:
    """Persist a pg_notify payload envelope to the pending-notify Redis hash.

    Stores a JSON envelope containing the payload, ``event_type``, ``task_id``,
    ``retry_count=0``, and ``next_retry_at`` (the earliest wall-clock time at
    which the first retry should fire, i.e. ``now + _RETRY_DELAYS_SECS[0]``).
    The SSE generator acks on receipt (HDEL); if no ack arrives the drain cycle
    re-emits the entry up to :data:`_MAX_RETRIES` times using the exponential
    delay schedule :data:`_RETRY_DELAYS_SECS`.

    Args:
        thread_id:  LangGraph UUID.
        event_type: SSE event name, e.g. ``"completed"``.
        task_id:    DB task PK (``None`` for session-level events like ``done``).
        raw:        JSON-encoded payload string.
    """
    try:
        client = await _get_publish_client()
        key = _pending_key(thread_id)
        field = _pending_field(event_type, task_id)
        next_retry_at = (datetime.now(timezone.utc).timestamp() + _RETRY_DELAYS_SECS[0])
        envelope = json.dumps({
            "raw": raw,
            "event_type": event_type,
            "task_id": task_id,
            "retry_count": 0,
            "next_retry_at": next_retry_at,
        })
        await client.hset(key, field, envelope)
        await client.expire(key, _PENDING_TTL_SECS)
        logger.debug(
            "[publisher.push_pending] event=%s field=%s thread_id=%s",
            event_type, field, thread_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[publisher.push_pending] failed event=%s thread_id=%s: %s",
            event_type, thread_id, exc,
        )


async def ack_pending_notify(thread_id: str, event_type: str, task_id: int | None) -> None:
    """Acknowledge delivery of a pg_notify event by removing it from the pending hash.

    Called by the SSE generator immediately after successfully yielding the
    event to the client.  A missing key is silently ignored.

    Args:
        thread_id:  LangGraph UUID.
        event_type: SSE event name that was delivered.
        task_id:    DB task PK (``None`` for session-level events).
    """
    try:
        client = await _get_publish_client()
        field = _pending_field(event_type, task_id)
        await client.hdel(_pending_key(thread_id), field)
        logger.debug(
            "[publisher.ack_pending] event=%s field=%s thread_id=%s",
            event_type, field, thread_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[publisher.ack_pending] failed event=%s thread_id=%s: %s",
            event_type, thread_id, exc,
        )


async def drain_pending_notify(thread_id: str) -> list[DrainEntry]:
    """Return all pending pg_notify entries that are due for re-emit.

    For each entry in the hash:

    - If ``retry_count >= _MAX_RETRIES`` (10): mark ``expired=True``, delete
      from the hash, and include in results — caller should log and discard.
    - If ``now < next_retry_at``: **skip** (not yet due) — entry stays in the
      hash unchanged and is NOT included in results.
    - Otherwise: increment ``retry_count``, compute the next ``next_retry_at``
      using :data:`_RETRY_DELAYS_SECS`, persist the updated envelope back to
      the hash, and include in results with ``expired=False`` so the caller
      re-emits the payload.

    Args:
        thread_id: LangGraph UUID.

    Returns:
        List of :class:`DrainEntry` objects.  Only entries that are expired or
        ready to re-emit are included; skipped (not-yet-due) entries are absent.
    """
    results: list[DrainEntry] = []
    try:
        client = await _get_publish_client()
        key = _pending_key(thread_id)
        entries: dict[str, str] = await client.hgetall(key)
        if not entries:
            return results

        now_ts = datetime.now(timezone.utc).timestamp()
        expired_fields: list[str] = []
        pipe = client.pipeline(transaction=False)

        for field, envelope_str in entries.items():
            try:
                envelope = json.loads(envelope_str)
            except Exception:  # noqa: BLE001
                # Corrupt entry — treat as expired and delete.
                expired_fields.append(field)
                continue

            retry_count: int = envelope.get("retry_count", 0)
            event_type: str = envelope.get("event_type", "")
            task_id_raw = envelope.get("task_id")
            task_id: int | None = int(task_id_raw) if task_id_raw is not None else None
            raw: str = envelope.get("raw", "{}")
            next_retry_at: float = envelope.get("next_retry_at", 0.0)

            if retry_count >= _MAX_RETRIES:
                expired_fields.append(field)
                results.append(DrainEntry(
                    field=field, raw=raw, event_type=event_type,
                    task_id=task_id, retry_count=retry_count, expired=True,
                ))
                continue

            if now_ts < next_retry_at:
                # Not yet due — leave envelope unchanged, don't include in results.
                continue

            # Due for re-emit: increment counter, schedule next retry.
            new_count = retry_count + 1
            delay_idx = min(new_count, len(_RETRY_DELAYS_SECS) - 1)
            new_next = now_ts + _RETRY_DELAYS_SECS[delay_idx]
            updated = dict(envelope)
            updated["retry_count"] = new_count
            updated["next_retry_at"] = new_next
            pipe.hset(key, field, json.dumps(updated))
            results.append(DrainEntry(
                field=field, raw=raw, event_type=event_type,
                task_id=task_id, retry_count=new_count, expired=False,
            ))

        if expired_fields:
            pipe.hdel(key, *expired_fields)

        await pipe.execute()

        live = sum(1 for e in results if not e.expired)
        dead = len(results) - live
        if results:
            logger.info(
                "[publisher.drain_pending] live=%d expired=%d thread_id=%s",
                live, dead, thread_id,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[publisher.drain_pending] failed thread_id=%s: %s",
            thread_id, exc,
        )
    return results


async def clear_pending_notify(thread_id: str) -> None:
    """Delete the pending-notify hash for *thread_id* on SSE teardown.

    Prevents stale entries accumulating when the SSE generator closes cleanly
    (e.g. client disconnected after receiving ``done``).

    Args:
        thread_id: LangGraph UUID.
    """
    try:
        client = await _get_publish_client()
        await client.delete(_pending_key(thread_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[publisher.clear_pending] failed thread_id=%s: %s",
            thread_id, exc,
        )


async def get_last_token_ms_ago(thread_id: str) -> int | None:
    """Return milliseconds since the most recent token was published for *thread_id*.

    Uses ``XREVRANGE`` to fetch the single most-recent entry from the thread's
    Redis Stream.  The entry ID encodes the publish timestamp as milliseconds
    since the Unix epoch (``<ms>-<seq>`` format).

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        Non-negative integer milliseconds since last token, or ``None`` if the
        stream key does not exist or contains no entries.
    """
    try:
        client = await _get_publish_client()
        key = stream_key(thread_id)
        entries = await client.xrevrange(key, "+", "-", count=1)
        if not entries:
            return None
        entry_id: str = entries[0][0]
        ms_ts = int(entry_id.split("-")[0])
        now_ms = int(time.time() * 1000)
        return max(0, now_ms - ms_ts)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[publisher.get_last_token_ms_ago] failed thread_id=%s: %s",
            thread_id, exc,
        )
        return None
