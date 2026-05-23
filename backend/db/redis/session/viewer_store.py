"""backend.db.redis.session.viewer_store — explicit per-thread/per-user viewer tracking.

Replaces indirect Centrifugo presence-stats polling with explicit Redis flags so
``stream_task`` can immediately determine viewer presence without relying on
WebSocket subscription timing.

Two flag types
--------------
* **App-level** ``fin:user:app_viewer:{user_id}`` — set whenever the user submits a
  query or explicitly opens a thread.  Signals that the browser is open.  Maps to
  :func:`~backend.centrifugo_mq.client.has_app_viewers`.

* **Thread-level** ``fin:thread:viewer:{thread_id}`` — set when the user submits this
  specific query or navigates to this thread.  Signals that the user is actively
  watching the thread.  Maps to
  :func:`~backend.centrifugo_mq.client.has_thread_viewers`.

Both keys are stored on Redis shard 0 (control-plane) with a 30-minute TTL,
which covers the longest possible LLM execution window.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_APP_VIEWER_KEY_PREFIX = "fin:user:app_viewer:"
_THREAD_VIEWER_KEY_PREFIX = "fin:thread:viewer:"
_TTL = 1800  # 30 minutes


def _app_viewer_key(user_id: str) -> str:
    return f"{_APP_VIEWER_KEY_PREFIX}{user_id}"


def _thread_viewer_key(thread_id: str) -> str:
    return f"{_THREAD_VIEWER_KEY_PREFIX}{thread_id}"


async def set_viewer(user_id: str, thread_id: str) -> None:
    """Mark *user_id* as having the app open and actively viewing *thread_id*.

    Sets both the app-level and thread-level viewer flags on Redis shard 0 with
    a 30-minute TTL.  Errors are logged but never raised — viewer detection is
    best-effort with a safe fallback of ``True`` in the callers.

    Args:
        user_id:   UUID of the user whose browser is open.
        thread_id: UUID of the thread the user is actively watching.
    """
    from backend.db.redis.client import get_client

    try:
        redis = await get_client(shard=0)
        pipe = redis.pipeline()
        pipe.set(_app_viewer_key(user_id), "1", ex=_TTL)
        pipe.set(_thread_viewer_key(thread_id), "1", ex=_TTL)
        await pipe.execute()
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[viewer_store] set_viewer failed user_id=%s thread_id=%s: %s",
            user_id, thread_id, exc,
        )


async def has_app_viewer(user_id: str) -> bool:
    """Return ``True`` if the app-level viewer flag for *user_id* is set.

    Args:
        user_id: UUID of the user to check.

    Returns:
        ``True`` if the flag exists in Redis; ``False`` if expired or absent.
        Defaults to ``False`` on Redis error (callers fall back to Centrifugo).
    """
    from backend.db.redis.client import get_client

    try:
        redis = await get_client(shard=0)
        val = await redis.get(_app_viewer_key(user_id))
        return val is not None
    except Exception as exc:  # noqa: BLE001
        logger.error("[viewer_store] has_app_viewer failed user_id=%s: %s", user_id, exc)
        return True  # Safe default — callers treat True as "publish events".


async def has_thread_viewer(thread_id: str) -> bool:
    """Return ``True`` if the thread-level viewer flag for *thread_id* is set.

    Args:
        thread_id: UUID of the thread to check.

    Returns:
        ``True`` if the flag exists in Redis; ``False`` if expired or absent.
        Defaults to ``False`` on Redis error (callers fall back to Centrifugo).
    """
    from backend.db.redis.client import get_client

    try:
        redis = await get_client(shard=0)
        val = await redis.get(_thread_viewer_key(thread_id))
        return val is not None
    except Exception as exc:  # noqa: BLE001
        logger.error("[viewer_store] has_thread_viewer failed thread_id=%s: %s", thread_id, exc)
        return True  # Safe default — callers treat True as "publish events".


async def clear_viewer(user_id: str, thread_id: str) -> None:
    """Remove the viewer flags for *user_id* and *thread_id* from Redis.

    Called by the frontend when its Centrifugo SSE subscription is torn down
    (thread completed, navigation away, page unload).  Clearing the flag ensures
    subsequent backend ``notify()`` calls treat the thread as unobserved and
    publish events to Centrifugo history only (no ACK retry loop), eliminating
    the 15–30 s CENTRIFUGO_003 NACK storm that occurs when the viewer flag
    outlives the actual WebSocket subscription.

    Args:
        user_id:   UUID of the user whose browser disconnected.
        thread_id: UUID of the thread the user stopped viewing.
    """
    from backend.db.redis.client import get_client

    try:
        redis = await get_client(shard=0)
        await redis.delete(_thread_viewer_key(thread_id), _app_viewer_key(user_id))
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[viewer_store] clear_viewer failed user_id=%s thread_id=%s: %s",
            user_id, thread_id, exc,
        )


__all__ = ["set_viewer", "has_app_viewer", "has_thread_viewer", "clear_viewer"]
