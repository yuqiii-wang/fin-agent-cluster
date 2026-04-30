"""Redis-backed query-status ACK store — lifecycle event delivery tracking.

Tracks which ``query_status`` phase events have been acknowledged by the
frontend client.  Complements :mod:`backend.db.redis.session.task_ack_store`
which covers task-level events.

When the runner publishes a ``query_status`` event via Centrifugo, it also
records the phase here as ``is_ack=False``.  The frontend sends a
``POST /stream/{thread_id}/status-ack`` request after receiving the event;
the assistant marks it ``is_ack=True``.

The assistant status-verifier background task reads unACKed phases and
re-publishes them so clients that miss events during a WS reconnect still
receive accurate phase information.

Key:   ``query_status_ack:{thread_id}``  (Redis Hash)
Field: ``{phase}``                        e.g. ``"received"``, ``"preparing"``
Value: JSON ``{"is_ack": bool, "published_at": str, "retry_count": int}``
TTL:   1800 s  (~30 min; matches the perf-test timeout upper bound)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from backend.db.redis.router import get_redis_router

logger = logging.getLogger(__name__)

_KEY_PREFIX = "query_status_ack:"
_TTL = 1800  # seconds

#: Ordered list of phases/events emitted during a normal query lifecycle.
#: ``"done"`` is the terminal event recorded after graph completion.
QUERY_STATUS_PHASES: tuple[str, ...] = ("received", "preparing", "ingesting", "digesting", "done")


def _key(thread_id: str) -> str:
    """Return the Redis hash key for query-status ACK tracking of *thread_id*."""
    return f"{_KEY_PREFIX}{thread_id}"


async def record_query_status_event(thread_id: str, phase: str) -> None:
    """Record a published query-status phase as pending ACK.

    Called immediately after :func:`~backend.sse_notifications.channel.publish_lifecycle`
    emits the ``query_status`` event.  Creates (or resets) the hash field for
    *phase* with ``is_ack=False`` and refreshes the TTL.

    Args:
        thread_id: LangGraph thread UUID.
        phase:     Phase label, e.g. ``"received"``, ``"preparing"``.
    """
    try:
        client = get_redis_router().get_client_for_thread(thread_id)
        key = _key(thread_id)
        now = datetime.now(timezone.utc).isoformat()
        envelope = json.dumps({"is_ack": False, "published_at": now, "retry_count": 0})
        await client.hset(key, phase, envelope)
        await client.expire(key, _TTL)
        logger.debug(
            "[query_status_ack] recorded phase=%s thread_id=%s",
            phase,
            thread_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[query_status_ack] record failed phase=%s thread_id=%s: %s",
            phase,
            thread_id,
            exc,
        )


async def ack_query_status_event(thread_id: str, phase: str) -> bool:
    """Mark a query-status phase as acknowledged by the frontend.

    Args:
        thread_id: LangGraph thread UUID.
        phase:     Phase label acknowledged by the client.

    Returns:
        ``True`` if the field existed and was updated; ``False`` if not found.
    """
    try:
        client = get_redis_router().get_client_for_thread(thread_id)
        key = _key(thread_id)
        raw = await client.hget(key, phase)
        if raw is None:
            logger.debug(
                "[query_status_ack] ack_not_found phase=%s thread_id=%s",
                phase,
                thread_id,
            )
            return False
        envelope = json.loads(raw)
        envelope["is_ack"] = True
        envelope["ack_at"] = datetime.now(timezone.utc).isoformat()
        await client.hset(key, phase, json.dumps(envelope))
        logger.debug(
            "[query_status_ack] acked phase=%s thread_id=%s",
            phase,
            thread_id,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[query_status_ack] ack failed phase=%s thread_id=%s: %s",
            phase,
            thread_id,
            exc,
        )
        return False


async def get_unacked_phases(thread_id: str) -> list[dict]:
    """Return all phases not yet acknowledged by the frontend.

    Each item in the returned list is a dict with:
    ``{"phase": str, "published_at": str, "retry_count": int}``.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        List of unACKed phase dicts, ordered by their natural phase sequence.
    """
    try:
        client = get_redis_router().get_client_for_thread(thread_id)
        key = _key(thread_id)
        raw_map: dict[str, str] = await client.hgetall(key)
        if not raw_map:
            return []
        unacked: list[dict] = []
        for phase, raw in raw_map.items():
            try:
                envelope = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue
            if not envelope.get("is_ack", True):
                unacked.append({
                    "phase": phase,
                    "published_at": envelope.get("published_at", ""),
                    "retry_count": envelope.get("retry_count", 0),
                })
        # Sort by canonical phase order; unknown phases go last.
        phase_order = {p: i for i, p in enumerate(QUERY_STATUS_PHASES)}
        unacked.sort(key=lambda x: phase_order.get(x["phase"], len(QUERY_STATUS_PHASES)))
        return unacked
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[query_status_ack] get_unacked failed thread_id=%s: %s",
            thread_id,
            exc,
        )
        return []


async def increment_phase_retry(thread_id: str, phase: str) -> None:
    """Increment the retry counter for an unACKed phase.

    Called by the assistant verifier each time it re-publishes the event.

    Args:
        thread_id: LangGraph thread UUID.
        phase:     Phase label being retried.
    """
    try:
        client = get_redis_router().get_client_for_thread(thread_id)
        key = _key(thread_id)
        raw = await client.hget(key, phase)
        if raw is None:
            return
        envelope = json.loads(raw)
        if envelope.get("is_ack", True):
            return  # already ACKed — no-op
        envelope["retry_count"] = envelope.get("retry_count", 0) + 1
        await client.hset(key, phase, json.dumps(envelope))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[query_status_ack] increment_retry failed phase=%s thread_id=%s: %s",
            phase,
            thread_id,
            exc,
        )


async def delete_query_status_ack(thread_id: str) -> None:
    """Delete the entire query-status ACK hash for *thread_id*.

    Called during :func:`~backend.db.redis.lock_manager.session_cleanup.cleanup_thread_session`.

    Args:
        thread_id: LangGraph thread UUID.
    """
    try:
        client = get_redis_router().get_client_for_thread(thread_id)
        await client.delete(_key(thread_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[query_status_ack] delete failed thread_id=%s: %s",
            thread_id,
            exc,
        )


async def store_stream_id_for_thread(thread_id: str, stream_id: str) -> None:
    """Store the stream_id associated with this thread's ingest session.

    Writes a ``_stream_id`` field into the existing
    ``query_status_ack:{thread_id}`` hash so the assistant status-verifier
    can include *stream_id* in its log lines without a separate Redis key.

    Args:
        thread_id: LangGraph thread UUID.
        stream_id: Streaming session UUID.
    """
    try:
        client = get_redis_router().get_client_for_thread(thread_id)
        await client.hset(_key(thread_id), "_stream_id", stream_id)
        await client.expire(_key(thread_id), _TTL)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "[query_status_ack] store_stream_id failed thread_id=%s: %s",
            thread_id,
            exc,
        )


async def get_stream_id_for_thread(thread_id: str) -> Optional[str]:
    """Return the stream_id stored for *thread_id*, or ``None`` if not set.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        The stream UUID string, or ``None`` if no ingest session recorded one.
    """
    try:
        client = get_redis_router().get_client_for_thread(thread_id)
        return await client.hget(_key(thread_id), "_stream_id")
    except Exception:  # noqa: BLE001
        return None


__all__ = [
    "QUERY_STATUS_PHASES",
    "record_query_status_event",
    "ack_query_status_event",
    "get_unacked_phases",
    "increment_phase_retry",
    "delete_query_status_ack",
    "store_stream_id_for_thread",
    "get_stream_id_for_thread",
]
