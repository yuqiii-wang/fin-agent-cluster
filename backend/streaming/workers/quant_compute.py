"""Celery worker — batch-consume ``fin:market:quant_compute`` stream.

Reads OHLCV bar payloads published by ``graph.utils.ohlcv.upsert_quant_stats``
and runs the full technical-indicator computation pipeline in a Celery worker
process.  This offloads the CPU-bound pandas-ta work (50–200 ms per symbol) out
of the FastAPI event loop and the shared thread pool, giving the main process
back both CPU time and thread-pool slots.

Fire-and-forget design
----------------------
``upsert_quant_stats`` publishes to the stream and returns immediately.  The
market-data agent already has the raw bars in graph state for downstream nodes;
the DB upsert is a write-aside operation whose latency is invisible to the user.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from backend.db import raw_conn
from backend.db.postgres.queries.fin_markets_quant import OhlcvStatsSQL
from backend.resource_api.quant_api.models import OHLCVBar
from backend.resource_api.quant_api.ohlcv_processor import compute_quant_stats
from backend.streaming.celery_app import celery_app
from backend.streaming.config import QUANT_COMPUTE
from backend.streaming.errors import STREAM_WORKER_BATCH_FAILED, STREAM_WORKER_MSG_FAILED
from backend.streaming.streams import (
    ensure_group,
    xack,
    xread_group,
)

logger = logging.getLogger(__name__)

_TOPIC = QUANT_COMPUTE


@celery_app.task(
    name=QUANT_COMPUTE.task_path,
    bind=True,
    max_retries=QUANT_COMPUTE.max_retries,
    default_retry_delay=QUANT_COMPUTE.retry_delay,
)
def consume_batch(self: Any) -> dict[str, int]:
    """Batch-consume quant-compute jobs from ``fin:market:quant_compute``.

    Called by the Celery beat scheduler every 5 seconds.  Each message
    contains serialised OHLCV bars plus metadata; this task runs
    ``compute_quant_stats`` (pandas-ta) and upserts the result to
    ``fin_markets.quant_stats``.

    Returns:
        Dict with ``processed`` and ``acked`` counts for monitoring.
    """
    try:
        return asyncio.run(_consume())
    except Exception as exc:
        logger.warning("[%s] quant_compute.consume_batch error: %s", STREAM_WORKER_BATCH_FAILED, exc)
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
            await _handle_job(msg_id, fields)
            acked.append(msg_id)
        except Exception as exc:
            logger.warning("[%s] quant_compute failed msg_id=%s: %s", STREAM_WORKER_MSG_FAILED, msg_id, exc)

    if acked:
        await xack(_TOPIC.stream_key, _TOPIC.consumer_group, *acked)

    logger.debug(
        "[quant_compute] processed=%d acked=%d",
        len(messages),
        len(acked),
    )
    return {"processed": len(messages), "acked": len(acked)}


async def _handle_job(msg_id: str, fields: dict[str, str]) -> None:
    """Process a single quant-compute job message.

    Deserialises bar data, runs CPU-bound ``compute_quant_stats`` in a thread
    (Celery is already on a separate OS process, so thread isolation keeps the
    worker's async loop responsive during computation), then upserts the result.

    Args:
        msg_id: Redis stream message ID.
        fields: Raw string fields from the stream entry.
    """
    symbol = fields.get("symbol", "")
    source = fields.get("source", "")
    interval = fields.get("interval", "1d")
    region = fields.get("region") or None
    currency_code = fields.get("currency_code", "USD") or "USD"

    bars_raw = fields.get("bars", "[]")
    try:
        bar_dicts: list[dict[str, Any]] = json.loads(bars_raw)
    except json.JSONDecodeError:
        logger.warning("[quant_compute] msg_id=%s: invalid bars JSON — skipping", msg_id)
        return

    bars = [OHLCVBar(**d) for d in bar_dicts]
    if not bars:
        logger.debug("[quant_compute] msg_id=%s: empty bars — skipping", msg_id)
        return

    logger.debug(
        "[quant_compute] msg_id=%s symbol=%s source=%s interval=%s bars=%d",
        msg_id, symbol, source, interval, len(bars),
    )

    rows = await asyncio.to_thread(
        compute_quant_stats,
        bar_lists=[bars],
        symbol=symbol,
        source=source,
        interval=interval,
    )
    if not rows:
        return

    for row in rows:
        row["region"] = region
        row["currency_code"] = currency_code

    async with raw_conn() as conn:
        async with conn.cursor() as cur:
            await cur.executemany(OhlcvStatsSQL.UPSERT, rows)

    logger.info(
        "[quant_compute] upserted %d rows symbol=%s interval=%s",
        len(rows), symbol, interval,
    )
