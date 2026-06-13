"""Node-scope SSE notify implementation."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from backend.centrifugo_mq.client import publish_node_event, publish_thread_event, has_app_viewers, has_thread_viewers
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
    node_id: str,
    event: str,
    payload: dict[str, Any],
    *,
    dedup_key: str | None = None,
    retry_interval: float = 5.0,
    max_retries: int = 6,
    require_ack: bool = True,
) -> bool:
    """Publish a node-scope SSE event and await frontend ACK with automatic retry.

    The event is published repeatedly at *retry_interval* second intervals until
    the frontend sends an ACK or explicit NACK, or *max_retries* attempts are
    exhausted.  On NACK or exhaustion a ``notification_failed`` event is
    published automatically.

    Args:
        thread_id:      LangGraph thread UUID.
        node_id:        Stable node identifier (use ``lifecycle.make_node_id``).
        event:          Event name string (e.g. ``"node_status"``).
        payload:        Additional fields merged into the published dict.
        dedup_key:      Ack key for this event.  Defaults to ``"node:{node_id}:{event}"``.
        retry_interval: Seconds to wait for a frontend ACK before re-publishing (default 3 s).
        max_retries:    Maximum number of publish attempts before giving up.
        require_ack:    When ``False`` the event is published once and the
                        function returns immediately without waiting for a
                        frontend ACK.  Use for informational status updates
                        (e.g. ``node_status: running``) where blocking the
                        graph on an ack would cause unnecessary delays.

    Returns:
        ``True`` if the frontend ACKed (or *require_ack* is ``False``);
        ``False`` on explicit NACK or exhaustion.
    """
    if not await has_app_viewers(thread_id):
        return True

    viewers_present = await has_thread_viewers(thread_id)
    nonce = uuid.uuid4().hex[:8]
    ack_key = f"{dedup_key or f'node:{node_id}:{event}'}:{nonce}"
    published_payload = {"event": event, "thread_id": thread_id, "node_id": node_id, "ack_key": ack_key, **payload}

    SSE_PUBLISHED.labels(scope="node", event=event).inc()

    # Fire-and-forget: publish once and return without waiting for ack.
    if not require_ack or not viewers_present:
        await publish_node_event(thread_id, published_payload)
        return True

    t0_total = time.monotonic()
    for attempt in range(max_retries):
        t_attempt = time.monotonic()
        SSE_PUBLISH_ATTEMPTS.labels(scope="node", event=event).inc()
        await publish_node_event(thread_id, published_payload)
        result = await wait_notify_ack(thread_id, ack_key, timeout=retry_interval)
        elapsed_attempt = (time.monotonic() - t_attempt) * 1000
        if result is True:
            total_s = time.monotonic() - t0_total
            SSE_ACK.labels(scope="node", event=event).inc()
            SSE_ACK_LATENCY.labels(scope="node", event=event).observe(total_s)
            logger.debug(
                "[sse:node] ack received node_id=%s event=%s attempt=%d attempt_ms=%.0f total_ms=%.0f",
                node_id, event, attempt, elapsed_attempt, total_s * 1000,
            )
            return True
        if result is False:
            if attempt >= 1:
                logger.error(
                    "[sse:node] NACK node_id=%s event=%s attempt=%d attempt_ms=%.0f",
                    node_id, event, attempt, elapsed_attempt,
                )
            else:
                logger.debug(
                    "[sse:node] NACK (1st attempt) node_id=%s event=%s attempt_ms=%.0f",
                    node_id, event, elapsed_attempt,
                )
            SSE_NACK.labels(scope="node", event=event, reason="explicit_nack").inc()
            break
        logger.debug(
            "[sse:node] ack timeout node_id=%s event=%s attempt=%d attempt_ms=%.0f -- retrying",
            node_id, event, attempt, elapsed_attempt,
        )

    if attempt >= 1:
        SSE_NACK.labels(scope="node", event=event, reason="exhausted").inc()
        logger.error(
            "[%s] node event NACK/exhausted thread_id=%s node_id=%s event=%s ack_key=%s total_ms=%.0f",
            CENTRIFUGO_SSE_NACK,
            thread_id,
            node_id,
            event,
            ack_key,
            (time.monotonic() - t0_total) * 1000,
        )
    else:
        logger.debug(
            "[sse:node] ack failed (1st attempt only) thread_id=%s node_id=%s event=%s ack_key=%s total_ms=%.0f",
            thread_id, node_id, event, ack_key, (time.monotonic() - t0_total) * 1000,
        )
    await publish_thread_event(
        thread_id,
        {
            "event": "notification_failed",
            "node_id": node_id,
            "original_event": event,
            "ack_key": ack_key,
        },
    )
    return False


__all__ = ["notify"]
