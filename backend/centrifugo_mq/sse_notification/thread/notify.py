"""Thread-scope SSE notify implementation."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from backend.centrifugo_mq.client import publish_thread_event, has_app_viewers, has_thread_viewers
from backend.centrifugo_mq.errors import CENTRIFUGO_SSE_NACK
from backend.centrifugo_mq.sse_notification.metrics import (
    SSE_ACK,
    SSE_ACK_LATENCY,
    SSE_NACK,
    SSE_PUBLISH_ATTEMPTS,
    SSE_PUBLISHED,
)
from backend.db.redis.session.notify_ack_store import wait_notify_ack

logger = logging.getLogger(__name__)


async def notify(
    thread_id: str,
    event: str,
    payload: dict[str, Any],
    *,
    dedup_key: str | None = None,
    retry_interval: float = 5.0,
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
        retry_interval: Seconds to wait for a frontend ACK before re-publishing (default 3 s).
        max_retries:    Maximum number of publish attempts before giving up.

    Returns:
        ``True`` if the frontend ACKed; ``False`` on explicit NACK or exhaustion.
    """
    # When the browser is closed skip publishing entirely -- the graph keeps
    # running silently.  When the app is open but the user is on a different
    # thread, publish once for Centrifugo history recovery without waiting for
    # an ACK (no subscriber is actively listening).  Full ACK cycle only when
    # the user is actively viewing this thread.
    if not await has_app_viewers(thread_id):
        return True

    # When no frontend client is subscribed, publish once and return -- the
    # event is stored in Centrifugo history (force_recovery) so the user sees
    # it when they open the thread later.  Skipping the ACK loop avoids
    # blocking the graph runner for ~18 s on background threads.
    viewers_present = await has_thread_viewers(thread_id)
    nonce = uuid.uuid4().hex[:8]
    ack_key = f"{dedup_key or f'thread:{event}'}:{nonce}"
    published_payload = {"event": event, "thread_id": thread_id, "ack_key": ack_key, **payload}

    SSE_PUBLISHED.labels(scope="thread", event=event).inc()

    if not viewers_present:
        await publish_thread_event(thread_id, published_payload)
        return True

    t0_total = time.monotonic()
    for attempt in range(max_retries):
        t_attempt = time.monotonic()
        SSE_PUBLISH_ATTEMPTS.labels(scope="thread", event=event).inc()
        await publish_thread_event(thread_id, published_payload)
        result = await wait_notify_ack(thread_id, ack_key, timeout=retry_interval)
        elapsed_attempt = (time.monotonic() - t_attempt) * 1000
        if result is True:
            total_s = time.monotonic() - t0_total
            SSE_ACK.labels(scope="thread", event=event).inc()
            SSE_ACK_LATENCY.labels(scope="thread", event=event).observe(total_s)
            logger.debug(
                "[sse:thread] ack received thread_id=%s event=%s attempt=%d attempt_ms=%.0f total_ms=%.0f",
                thread_id, event, attempt, elapsed_attempt, total_s * 1000,
            )
            return True
        if result is False:
            if attempt >= 1:
                logger.error(
                    "[sse:thread] NACK thread_id=%s event=%s attempt=%d attempt_ms=%.0f",
                    thread_id, event, attempt, elapsed_attempt,
                )
            else:
                logger.debug(
                    "[sse:thread] NACK (1st attempt) thread_id=%s event=%s attempt_ms=%.0f",
                    thread_id, event, elapsed_attempt,
                )
            SSE_NACK.labels(scope="thread", event=event, reason="explicit_nack").inc()
            break
        logger.debug(
            "[sse:thread] ack timeout thread_id=%s event=%s attempt=%d attempt_ms=%.0f -- retrying",
            thread_id, event, attempt, elapsed_attempt,
        )

    if attempt >= 1:
        SSE_NACK.labels(scope="thread", event=event, reason="exhausted").inc()
        logger.error(
            "[%s] thread event NACK/exhausted thread_id=%s event=%s ack_key=%s total_ms=%.0f",
            CENTRIFUGO_SSE_NACK,
            thread_id,
            event,
            ack_key,
            (time.monotonic() - t0_total) * 1000,
        )
    else:
        logger.debug(
            "[sse:thread] ack failed (1st attempt only) thread_id=%s event=%s ack_key=%s total_ms=%.0f",
            thread_id, event, ack_key, (time.monotonic() - t0_total) * 1000,
        )
    await publish_thread_event(
        thread_id,
        {"event": "notification_failed", "original_event": event, "ack_key": ack_key},
    )
    return False


__all__ = ["notify"]
