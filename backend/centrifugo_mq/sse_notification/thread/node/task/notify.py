"""Task-scope SSE notify implementation."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from backend.centrifugo_mq.client import publish_task_event, has_app_viewers, has_thread_viewers
from backend.centrifugo_mq.errors import CENTRIFUGO_SSE_NACK
from backend.db.redis.session.notify_ack_store import wait_notify_ack

logger = logging.getLogger(__name__)


async def notify(
    thread_id: str,
    task_id: str,
    event: str,
    payload: dict[str, Any],
    *,
    dedup_key: str | None = None,
    retry_interval: float = 3.0,
    max_retries: int = 6,
) -> bool:
    """Publish a task-scope SSE event and await frontend ACK with automatic retry.

    The event is published repeatedly at *retry_interval* second intervals until
    the frontend sends an ACK or explicit NACK, or *max_retries* attempts are
    exhausted.  On NACK or exhaustion a ``task_status: failed`` event is
    published so the frontend always receives a terminal state for the task.

    Args:
        thread_id:      LangGraph thread UUID.
        task_id:        Task UUID (use ``lifecycle.make_task_id``).
        event:          Event name string (e.g. ``"task_status"``).
        payload:        Additional fields merged into the published dict.
        dedup_key:      Ack key for this event.  Defaults to
                        ``"task:{task_id}:{event}"``.
        retry_interval: Seconds to wait for a frontend ACK before re-publishing (default 3 s).
        max_retries:    Maximum number of publish attempts before giving up.

    Returns:
        ``True`` if the frontend ACKed; ``False`` on explicit NACK or exhaustion.
    """
    if not await has_app_viewers(thread_id):
        return True

    viewers_present = await has_thread_viewers(thread_id)
    nonce = uuid.uuid4().hex[:8]
    ack_key = f"{dedup_key or f'task:{task_id}:{event}'}:{nonce}"
    published_payload = {"event": event, "thread_id": thread_id, "task_id": task_id, "ack_key": ack_key, **payload}

    if not viewers_present:
        await publish_task_event(thread_id, published_payload)
        return True

    t0_total = time.monotonic()
    for attempt in range(max_retries):
        t_attempt = time.monotonic()
        await publish_task_event(thread_id, published_payload)
        result = await wait_notify_ack(thread_id, ack_key, timeout=retry_interval)
        elapsed_attempt = (time.monotonic() - t_attempt) * 1000
        if result is True:
            logger.debug(
                "[sse:task] ack received task_id=%s event=%s attempt=%d attempt_ms=%.0f total_ms=%.0f",
                task_id, event, attempt, elapsed_attempt, (time.monotonic() - t0_total) * 1000,
            )
            return True
        if result is False:
            if attempt >= 1:
                logger.error(
                    "[sse:task] NACK task_id=%s event=%s attempt=%d attempt_ms=%.0f",
                    task_id, event, attempt, elapsed_attempt,
                )
            else:
                logger.debug(
                    "[sse:task] NACK (1st attempt) task_id=%s event=%s attempt_ms=%.0f",
                    task_id, event, elapsed_attempt,
                )
            break
        logger.debug(
            "[sse:task] ack timeout task_id=%s event=%s attempt=%d attempt_ms=%.0f — retrying",
            task_id, event, attempt, elapsed_attempt,
        )

    if attempt >= 1:
        logger.error(
            "[%s] task event NACK/exhausted thread_id=%s task_id=%s event=%s ack_key=%s total_ms=%.0f",
            CENTRIFUGO_SSE_NACK,
            thread_id,
            task_id,
            event,
            ack_key,
            (time.monotonic() - t0_total) * 1000,
        )
    else:
        logger.debug(
            "[sse:task] ack failed (1st attempt only) thread_id=%s task_id=%s event=%s ack_key=%s total_ms=%.0f",
            thread_id, task_id, event, ack_key, (time.monotonic() - t0_total) * 1000,
        )
    await publish_task_event(
        thread_id,
        {
            "event": "task_status",
            "task_id": task_id,
            "status": "failed",
            "reason": "ack_timeout",
        },
    )
    return False


__all__ = ["notify"]
