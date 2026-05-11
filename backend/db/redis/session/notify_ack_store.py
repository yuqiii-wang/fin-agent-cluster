"""backend.db.redis.session.notify_ack_store — BLPOP-based ACK/NACK signaling for SSE notifications.

After an SSE event is published to the frontend via Centrifugo, the publisher
awaits a signal on a per-event Redis list.  When the frontend confirms receipt
through the Centrifugo RPC ack channel, :func:`signal_notify_ack` pushes ``"1"``
to unblock the waiter.  An explicit NACK pushes ``"0"``; a BLPOP timeout is
treated as an implicit NACK.

Key format::

    session:notify_ack:{thread_id}:{ack_key}

where *ack_key* matches the ``dedup_key`` used in the corresponding
:func:`~backend.centrifugo_mq.sse_notification.thread.notify` call
(e.g. ``"task:{task_id}:completed"`` or ``"thread:done:completed"``).
"""

from __future__ import annotations

import logging

from backend.db.redis import get_client, shard_for_thread

logger = logging.getLogger(__name__)

_KEY_PREFIX = "session:notify_ack:"
_TTL = 300  # 5 minutes


def _list_key(thread_id: str, ack_key: str) -> str:
    return f"{_KEY_PREFIX}{thread_id}:{ack_key}"


async def wait_notify_ack(thread_id: str, ack_key: str, timeout: float = 3.0) -> bool | None:
    """Block (async) until an ACK or NACK signal arrives, or *timeout* seconds elapse.

    Uses Redis BLPOP so no polling occurs — the coroutine yields to the event
    loop and resumes only when a value is pushed or the timeout fires.

    Args:
        thread_id: LangGraph thread UUID — determines the Redis shard.
        ack_key:   Unique key for this notification (e.g. ``"task:{task_id}:completed"``).
        timeout:   Maximum seconds to wait per attempt before returning ``None``.

    Returns:
        ``True`` if an ACK was received; ``False`` on explicit NACK; ``None`` on timeout.
    """
    try:
        redis = await get_client(shard_for_thread(thread_id))
        result = await redis.blpop([_list_key(thread_id, ack_key)], timeout=max(1, int(timeout)))
        if result is None:
            return None  # timeout → caller decides whether to retry
        _, value = result
        return value == "1"
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[notify_ack_store] wait failed thread_id=%s ack_key=%s: %s",
            thread_id,
            ack_key,
            exc,
        )
        return None


async def signal_notify_ack(thread_id: str, ack_key: str) -> None:
    """Signal ACK for a pending :func:`wait_notify_ack` call.

    Should be called by the RPC proxy when the frontend confirms receipt of
    the corresponding SSE event.

    Args:
        thread_id: LangGraph thread UUID.
        ack_key:   Must match the key used in :func:`wait_notify_ack`.
    """
    try:
        redis = await get_client(shard_for_thread(thread_id))
        key = _list_key(thread_id, ack_key)
        await redis.rpush(key, "1")
        await redis.expire(key, _TTL)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[notify_ack_store] signal_ack failed thread_id=%s ack_key=%s: %s",
            thread_id,
            ack_key,
            exc,
        )


async def signal_notify_nack(thread_id: str, ack_key: str) -> None:
    """Signal explicit NACK for a pending :func:`wait_notify_ack` call.

    Args:
        thread_id: LangGraph thread UUID.
        ack_key:   Must match the key used in :func:`wait_notify_ack`.
    """
    try:
        redis = await get_client(shard_for_thread(thread_id))
        key = _list_key(thread_id, ack_key)
        await redis.rpush(key, "0")
        await redis.expire(key, _TTL)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[notify_ack_store] signal_nack failed thread_id=%s ack_key=%s: %s",
            thread_id,
            ack_key,
            exc,
        )


__all__ = ["wait_notify_ack", "signal_notify_ack", "signal_notify_nack"]
