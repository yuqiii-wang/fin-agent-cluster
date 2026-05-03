"""Redis-backed task ACK store — SSE delivery state tracking per LangGraph session.

Tracks per-task SSE delivery state (ACK flag, retry count) in a Redis hash keyed
by ``task_ack:{thread_id}``.  Each field is ``{task_id}:{status}`` and its value
is a JSON envelope with delivery metadata.

This is **SSE delivery bookkeeping only** — it records whether the client has
received the SSE notification for each task status transition.  The authoritative
task business state (status, input, output) lives in ``fin_agents.tasks`` in
PostgreSQL.

Key:    ``task_ack:{thread_id}``  (Redis Hash)
Field:  ``{task_id}:{status}``  e.g. ``"abc-123:digesting"``, ``"abc-123:completed"``
Value:  JSON ``{"retry_count": int, "is_ack": bool, "ack_at": str|null, "created_at": str}``
TTL:    3600 s  (auto-expires; also explicitly deleted by
        :func:`~backend.db.redis.lock_manager.session_cleanup.cleanup_thread_session`)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from backend.db.redis.router import get_redis_router

logger = logging.getLogger(__name__)

_TASK_ACK_PREFIX = "task_ack:"
_TASK_ACK_TTL = 3600  # seconds

#: Maps SSE event_type strings to the corresponding step status values.
_EVENT_TO_STEP_STATUS: dict[str, str] = {
    "started": "digesting",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
}


def _task_ack_key(thread_id: str) -> str:
    """Return the Redis hash key for the task ACK store of *thread_id*.

    Args:
        thread_id: LangGraph UUID.
    """
    return f"{_TASK_ACK_PREFIX}{thread_id}"


def _field(task_id: str, status: str) -> str:
    """Return the hash field for a specific task+status combination.

    Args:
        task_id: Task primary key (UUID string).
        status:    Step status string, e.g. ``"digesting"``.
    """
    return f"{task_id}:{status}"


async def record_task_step(thread_id: str, task_id: str, status: str) -> None:
    """Record a new task step in the task ACK store.

    Creates a hash field ``{task_id}:{status}`` under ``task_ack:{thread_id}``.

    Args:
        thread_id: LangGraph UUID.
        task_id: Task primary key (UUID string).
        status:    Step status, e.g. ``"digesting"``, ``"completed"``.
    """
    try:
        client = get_redis_router().get_client_for_thread(thread_id)
        key = _task_ack_key(thread_id)
        field = _field(task_id, status)
        envelope = json.dumps({
            "retry_count": 0,
            "is_ack": False,
            "ack_at": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        await client.hset(key, field, envelope)
        await client.expire(key, _TASK_ACK_TTL)
        logger.debug(
            "[task_ack_store.record] task_id=%s status=%s thread_id=%s",
            task_id, status, thread_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[task_ack_store.record] failed task_id=%s status=%s thread_id=%s: %s",
            task_id, status, thread_id, exc,
        )


async def ack_task_step(
    thread_id: str,
    task_id: Optional[str],
    event_type: str,
) -> None:
    """Mark a task step as acknowledged in the task ACK store.

    Args:
        thread_id:  LangGraph UUID.
        task_id:  Task primary key, or ``None``/``""`` for session-level events.
        event_type: SSE event name, e.g. ``"completed"``.
    """
    if not task_id:
        return
    step_status = _EVENT_TO_STEP_STATUS.get(event_type)
    if not step_status:
        return
    try:
        client = get_redis_router().get_client_for_thread(thread_id)
        key = _task_ack_key(thread_id)
        field = _field(task_id, step_status)
        raw = await client.hget(key, field)
        if raw is None:
            logger.debug(
                "[task_ack_store.ack] field not found task_id=%s event=%s thread_id=%s",
                task_id, event_type, thread_id,
            )
            return
        envelope: dict = json.loads(raw)
        if envelope.get("is_ack"):
            return  # already acked
        envelope["is_ack"] = True
        envelope["ack_at"] = datetime.now(timezone.utc).isoformat()
        await client.hset(key, field, json.dumps(envelope))
        logger.debug(
            "[task_ack_store.ack] task_id=%s event=%s status=%s thread_id=%s",
            task_id, event_type, step_status, thread_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[task_ack_store.ack] failed task_id=%s event=%s thread_id=%s: %s",
            task_id, event_type, thread_id, exc,
        )


async def increment_task_step_retry(
    thread_id: str,
    task_id: Optional[str],
    event_type: str,
) -> None:
    """Increment the retry counter for an unacked task step.

    Args:
        thread_id:  LangGraph UUID.
        task_id:  Task primary key, or ``None``/``""`` for session-level events.
        event_type: SSE event name, e.g. ``"completed"``.
    """
    if not task_id:
        return
    step_status = _EVENT_TO_STEP_STATUS.get(event_type)
    if not step_status:
        return
    try:
        client = get_redis_router().get_client_for_thread(thread_id)
        key = _task_ack_key(thread_id)
        field = _field(task_id, step_status)
        raw = await client.hget(key, field)
        if raw is None:
            return
        envelope: dict = json.loads(raw)
        if envelope.get("is_ack"):
            return
        envelope["retry_count"] = envelope.get("retry_count", 0) + 1
        await client.hset(key, field, json.dumps(envelope))
        logger.debug(
            "[task_ack_store.retry] task_id=%s event=%s retry_count=%d thread_id=%s",
            task_id, event_type, envelope["retry_count"], thread_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[task_ack_store.retry] failed task_id=%s event=%s thread_id=%s: %s",
            task_id, event_type, thread_id, exc,
        )


__all__ = [
    "record_task_step",
    "ack_task_step",
    "increment_task_step_retry",
]
