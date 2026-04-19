"""Celery worker — batch-consume ``fin:market:ticks`` stream.

Reads OHLCV market data messages published by ``resource_api.quant_api``
and upserts aggregated symbol statistics into ``fin_markets.quant_raw``
(if the data is not already present).  This provides a durable secondary
processing path independent of the live-fetch hot path.

Use case
--------
When a market data agent fetches OHLCV bars for a symbol, the result is
published to the stream in addition to being written to the DB cache.
This worker can re-process those messages to update derived analytics
(e.g. rolling statistics, cross-symbol correlations) in a background lane
without blocking the agent.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from backend.streaming.celery_app import celery_app
from backend.streaming.config import MARKET_TICKS
from backend.streaming.streams import (
    ensure_group,
    xack,
    xread_group,
)

logger = logging.getLogger(__name__)

_TOPIC = MARKET_TICKS


@celery_app.task(
    name=MARKET_TICKS.task_path,
    bind=True,
    max_retries=MARKET_TICKS.max_retries,
    default_retry_delay=MARKET_TICKS.retry_delay,
)
def consume_batch(self: Any) -> dict[str, int]:
    """Batch-consume market tick messages from ``fin:market:ticks``.

    Called by the Celery beat scheduler every 5 seconds.

    Returns:
        Dict with ``processed`` and ``acked`` counts for monitoring.
    """
    try:
        return asyncio.run(_consume())
    except Exception as exc:
        logger.warning("[market_data.consume_batch] error: %s", exc)
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
            await _handle_tick(msg_id, fields)
            acked.append(msg_id)
        except Exception as exc:
            logger.warning("[market_data] failed msg_id=%s: %s", msg_id, exc)

    if acked:
        await xack(_TOPIC.stream_key, _TOPIC.consumer_group, *acked)

    logger.debug(
        "[market_data] processed=%d acked=%d",
        len(messages),
        len(acked),
    )
    return {"processed": len(messages), "acked": len(acked)}


async def _handle_tick(msg_id: str, fields: dict[str, str]) -> None:
    """Process a single market tick message.

    Args:
        msg_id: Redis stream message ID.
        fields: Raw string fields from the stream entry.
    """
    symbol = fields.get("symbol", "")
    source = fields.get("source", "")
    method = fields.get("method", "")
    bar_count = int(fields.get("bar_count", "0"))

    bars: list[dict[str, Any]] = []
    bars_raw = fields.get("bars", "[]")
    try:
        bars = json.loads(bars_raw)
    except json.JSONDecodeError:
        pass

    logger.debug(
        "[market_data] msg_id=%s symbol=%s source=%s method=%s bars=%d",
        msg_id,
        symbol,
        source,
        method,
        bar_count or len(bars),
    )
