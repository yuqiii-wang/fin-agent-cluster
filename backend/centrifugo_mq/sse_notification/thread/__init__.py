"""centrifugo_mq.sse_notification.thread — thread-scope SSE notification.

Publishes a thread-level SSE event then awaits an ACK from the frontend via
Redis BLPOP.  On NACK or timeout a ``notification_failed`` event is published
automatically.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from backend.centrifugo_mq.client import publish_thread_event
from backend.centrifugo_mq.errors import CENTRIFUGO_SSE_NACK
from backend.db.redis.session.notify_ack_store import wait_notify_ack

logger = logging.getLogger(__name__)


async def notify(
    thread_id: str,
    event: str,
    payload: dict[str, Any],
    *,
    dedup_key: str | None = None,
    retry_interval: float = 3.0,
    max_retries: int = 6,
) -> bool:
    """Publish a thread-scope SSE event and await frontend ACK with automatic retry.

    The event is published repeatedly at *retry_interval* second intervals until
    the frontend sends an ACK or explicit NACK, or *max_retries* attempts are
    exhausted.  On NACK or exhaustion a ``notification_failed`` event is
    published automatically.

    Args:
        thread_id:      LangGraph thread UUID.
        event:          Event name string (e.g. ``"done"``, ``"query_status"``).
        payload:        Additional fields merged into the published dict.
        dedup_key:      Ack key for this event.  Defaults to ``"thread:{event}"``.
                        Use a more specific key when the same event name recurs
                        (e.g. ``f"thread:query_status:{phase}"``).
        retry_interval: Seconds to wait for a frontend ACK before re-publishing (default 3 s).
        max_retries:    Maximum number of publish attempts before giving up.

    Returns:
        ``True`` if the frontend ACKed; ``False`` on explicit NACK or exhaustion.
    """
    # Per-invocation nonce to prevent false positives in confirmedAckKeysRef
    # when Centrifugo replays ack_confirmed events from channel history.
    nonce = uuid.uuid4().hex[:8]
    ack_key = f"{dedup_key or f'thread:{event}'}:{nonce}"
    published_payload = {"event": event, "thread_id": thread_id, "ack_key": ack_key, **payload}

    t0_total = time.monotonic()
    for attempt in range(max_retries):
        t_attempt = time.monotonic()
        await publish_thread_event(thread_id, published_payload)
        result = await wait_notify_ack(thread_id, ack_key, timeout=retry_interval)
        elapsed_attempt = (time.monotonic() - t_attempt) * 1000
        if result is True:
            logger.debug(
                "[sse:thread] ack received thread_id=%s event=%s attempt=%d attempt_ms=%.0f total_ms=%.0f",
                thread_id, event, attempt, elapsed_attempt, (time.monotonic() - t0_total) * 1000,
            )
            return True
        if result is False:
            # Explicit NACK — stop retrying immediately.
            logger.error(
                "[sse:thread] NACK thread_id=%s event=%s attempt=%d attempt_ms=%.0f",
                thread_id, event, attempt, elapsed_attempt,
            )
            break
        # result is None → timeout → retry
        logger.debug(
            "[sse:thread] ack timeout thread_id=%s event=%s attempt=%d attempt_ms=%.0f — retrying",
            thread_id, event, attempt, elapsed_attempt,
        )

    logger.error(
        "[%s] thread event NACK/exhausted thread_id=%s event=%s ack_key=%s total_ms=%.0f",
        CENTRIFUGO_SSE_NACK,
        thread_id,
        event,
        ack_key,
        (time.monotonic() - t0_total) * 1000,
    )
    await publish_thread_event(
        thread_id,
        {"event": "notification_failed", "original_event": event, "ack_key": ack_key},
    )
    return False


__all__ = ["notify"]
