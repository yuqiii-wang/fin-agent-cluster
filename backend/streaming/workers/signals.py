"""Celery worker — batch-consume ``fin:signals:trade`` stream.

Reads trade signal messages published by the decision-maker agent and
performs secondary processing:

1. **Logging** — persists a structured record of each signal for audit.
2. **Risk gate** — future hook: reject signals that violate position limits
   or drawdown thresholds before they reach order management.
3. **Strategy aggregation** — future hook: combine signals from multiple
   agents into a consolidated view.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.streaming.celery_app import celery_app
from backend.streaming.config import TRADE_SIGNALS
from backend.streaming.streams import (
    ensure_group,
    xack,
    xread_group,
)

logger = logging.getLogger(__name__)

_TOPIC = TRADE_SIGNALS


@celery_app.task(
    name=TRADE_SIGNALS.task_path,
    bind=True,
    max_retries=TRADE_SIGNALS.max_retries,
    default_retry_delay=TRADE_SIGNALS.retry_delay,
)
def consume_batch(self: Any) -> dict[str, int]:
    """Batch-consume trade signal messages from ``fin:signals:trade``.

    Called by the Celery beat scheduler every 5 seconds.

    Returns:
        Dict with ``processed`` and ``acked`` counts for monitoring.
    """
    try:
        return asyncio.run(_consume())
    except Exception as exc:
        logger.warning("[signals.consume_batch] error: %s", exc)
        raise self.retry(exc=exc)


async def _consume() -> dict[str, int]:
    """Inner async implementation of the batch consumer.

    Returns:
        Stats dict ``{processed, acked}``.
    """
    await ensure_group(_TOPIC.stream_key, _TOPIC.consumer_group)

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
            _handle_signal(msg_id, fields)
            acked.append(msg_id)
        except Exception as exc:
            logger.warning("[signals] failed msg_id=%s: %s", msg_id, exc)

    if acked:
        await xack(_TOPIC.stream_key, _TOPIC.consumer_group, *acked)

    logger.debug(
        "[signals] processed=%d acked=%d",
        len(messages),
        len(acked),
    )
    return {"processed": len(messages), "acked": len(acked)}


def _handle_signal(msg_id: str, fields: dict[str, str]) -> None:
    """Log and gate a single trade signal.

    Args:
        msg_id: Redis stream message ID.
        fields: Raw string fields from the stream entry.
    """
    thread_id = fields.get("thread_id", "")
    symbol = fields.get("symbol", "")
    signal = fields.get("signal", "")
    confidence = fields.get("confidence", "0")
    reasoning = fields.get("reasoning", "")

    logger.info(
        "[signals] msg_id=%s thread=%s symbol=%s signal=%s confidence=%s reasoning=%s",
        msg_id,
        thread_id,
        symbol,
        signal,
        confidence,
        reasoning[:120],
    )
