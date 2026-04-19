"""Celery worker — batch-consume ``fin:graph:events`` stream.

Reads unacknowledged messages from the ``celery-graph`` consumer group and
logs analytics-level statistics (event type distribution, task latencies).
The graph nodes already persist task rows to PostgreSQL directly; this worker
provides a secondary processing lane for observability without blocking the
hot path.

Pending messages (delivered but not ACKed due to a crash) are re-processed
on the next invocation via a separate pending-delivery pass.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.streaming.celery_app import celery_app
from backend.streaming.config import GRAPH_EVENTS
from backend.streaming.streams import (
    ensure_group,
    xack,
    xread_group,
)

logger = logging.getLogger(__name__)

_TOPIC = GRAPH_EVENTS


@celery_app.task(
    name=GRAPH_EVENTS.task_path,
    bind=True,
    max_retries=GRAPH_EVENTS.max_retries,
    default_retry_delay=GRAPH_EVENTS.retry_delay,
)
def consume_batch(self: Any) -> dict[str, int]:
    """Batch-consume graph event messages from ``fin:graph:events``.

    Called by the Celery beat scheduler every 2 seconds.  Processes up to
    ``_BATCH_SIZE`` pending messages per invocation.

    Returns:
        Dict with ``processed`` and ``acked`` counts for monitoring.
    """
    try:
        return asyncio.run(_consume())
    except Exception as exc:
        logger.warning("[graph_events.consume_batch] error: %s", exc)
        raise self.retry(exc=exc)


async def _consume() -> dict[str, int]:
    """Inner async implementation of the batch consumer.

    Returns:
        Stats dict ``{processed, acked}``.
    """
    await ensure_group(_TOPIC.stream_key, _TOPIC.consumer_group)

    # Re-deliver any unacknowledged pending messages first
    pending = await xread_group(
        _TOPIC.stream_key,
        _TOPIC.consumer_group,
        _TOPIC.consumer_name,
        count=_TOPIC.batch_size,
        block_ms=0,
        pending=True,
    )

    messages = pending or await xread_group(
        _TOPIC.stream_key,
        _TOPIC.consumer_group,
        _TOPIC.consumer_name,
        count=_TOPIC.batch_size,
        block_ms=500,
    )

    if not messages:
        return {"processed": 0, "acked": 0}

    acked: list[str] = []
    for msg_id, fields in messages:
        try:
            _handle_event(msg_id, fields)
            acked.append(msg_id)
        except Exception as exc:
            logger.warning("[graph_events] failed msg_id=%s: %s", msg_id, exc)

    if acked:
        await xack(_TOPIC.stream_key, _TOPIC.consumer_group, *acked)

    logger.debug(
        "[graph_events] processed=%d acked=%d",
        len(messages),
        len(acked),
    )
    return {"processed": len(messages), "acked": len(acked)}


def _handle_event(msg_id: str, fields: dict[str, str]) -> None:
    """Log and track a single graph event for analytics.

    Args:
        msg_id: Redis stream message ID.
        fields: Raw string fields from the stream entry.
    """
    event_type = fields.get("event_type", "unknown")
    thread_id = fields.get("thread_id", "")
    task_key = fields.get("task_key", "")

    logger.debug(
        "[graph_events] msg_id=%s thread=%s event_type=%s task_key=%s",
        msg_id,
        thread_id,
        event_type,
        task_key,
    )
