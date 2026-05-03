"""Redis-backed pause signal for LangGraph interrupt-based pause/resume.

When ``POST /query/{thread_id}/pause`` is received the signal is written here.
The running :func:`~backend.graph.runner._invoke_with_auto_approve` loop checks
this flag at every ``interrupt()`` checkpoint; when found it declines to
auto-resume, letting LangGraph preserve the interrupt checkpoint so the graph
can be resumed later with ``Command(resume=True)``.

Key schema
----------
``fin:pause:{thread_id}``
    Set to ``"1"`` with TTL ``_PAUSE_TTL`` by :func:`set_pause_signal`.
    Atomically consumed (GET + DEL) by :func:`check_and_consume_pause_signal`.
    The TTL prevents stale signals from blocking a future run.

Shard routing uses ``thread_id`` — consistent with all other per-thread keys.
"""

from __future__ import annotations

import logging

from backend.db.redis.router import get_redis_router

logger = logging.getLogger(__name__)

_PAUSE_PREFIX: str = "fin:pause:"
_PAUSE_TTL: int = 3600  # seconds — auto-expire if never consumed


async def set_pause_signal(thread_id: str) -> None:
    """Set the pause signal for *thread_id*.

    The next ``interrupt()`` boundary encountered by the graph runner will
    decline auto-resume and allow LangGraph to persist the interrupt checkpoint.

    Args:
        thread_id: LangGraph thread UUID.
    """
    client = get_redis_router().get_client_for_thread(thread_id)
    key = f"{_PAUSE_PREFIX}{thread_id}"
    await client.setex(key, _PAUSE_TTL, "1")
    logger.info("[pause_signal] set thread_id=%s", thread_id)


async def check_and_consume_pause_signal(thread_id: str) -> bool:
    """Atomically check and delete the pause signal for *thread_id*.

    Uses a Redis pipeline (GETDEL) so the signal is consumed exactly once even
    under concurrent runner/API calls.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        ``True`` if a pause signal was pending (and is now consumed).
    """
    client = get_redis_router().get_client_for_thread(thread_id)
    key = f"{_PAUSE_PREFIX}{thread_id}"
    value = await client.getdel(key)
    found = value is not None
    if found:
        logger.info("[pause_signal] consumed thread_id=%s", thread_id)
    return found


async def delete_pause_signal(thread_id: str) -> None:
    """Delete any pending pause signal for *thread_id* (cleanup on resume/cancel).

    Args:
        thread_id: LangGraph thread UUID.
    """
    client = get_redis_router().get_client_for_thread(thread_id)
    key = f"{_PAUSE_PREFIX}{thread_id}"
    await client.delete(key)
    logger.debug("[pause_signal] deleted thread_id=%s", thread_id)


__all__ = [
    "set_pause_signal",
    "check_and_consume_pause_signal",
    "delete_pause_signal",
]
