"""Redis Streams token subscriber helpers.

Provides the ``read_stream`` async context manager that opens a dedicated
Redis connection per SSE subscriber and pumps token messages from the thread's
Redis Stream (XREAD BLOCK) onto an ``asyncio.Queue`` for consumption by the
SSE generator.

Only **token** events travel through Redis Streams.  Task lifecycle events
(started, completed, failed, done) are received via PostgreSQL NOTIFY.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis

from backend.config import get_settings
from backend.db.redis.publisher import stream_key

logger = logging.getLogger(__name__)

# Block timeout for XREAD in milliseconds.  The pump wakes up at least this
# often so that the context-manager cleanup path can cancel the task promptly.
_BLOCK_MS = 2_000

# Global XREAD audit counter for the 5-min summary.
_xread_count: int = 0
_xread_last_flush: float = time.monotonic()
_xread_lock = threading.Lock()
_SUMMARY_INTERVAL: float = 300.0  # 5 minutes


def _track_xread(n: int = 1) -> None:
    """Increment the XREAD counter by *n* and emit a 5-min summary when due.

    Args:
        n: Number of messages received in this XREAD batch.
    """
    global _xread_count, _xread_last_flush
    with _xread_lock:
        _xread_count += n
        now = time.monotonic()
        if now - _xread_last_flush >= _SUMMARY_INTERVAL:
            count = _xread_count
            _xread_count = 0
            _xread_last_flush = now
            logger.info(
                "[Redis Streams 5-min summary]\n"
                "  tokens:* XREAD (subscriber/SSE): %d reads",
                count,
            )


@asynccontextmanager
async def read_stream(
    thread_id: str,
) -> AsyncGenerator[asyncio.Queue[str], None]:
    """Async context manager that reads token events from the thread's Redis Stream.

    Opens a dedicated Redis connection per subscriber and spawns a background
    task that uses ``XREAD BLOCK`` to pump new stream entries onto an
    ``asyncio.Queue``.  Both the task and the connection are cleaned up on
    context-manager exit.

    Args:
        thread_id: LangGraph thread ID to read from.

    Yields:
        Queue of raw JSON token payloads (strings).
    """
    settings = get_settings()
    client: aioredis.Redis = aioredis.from_url(
        settings.DATABASE_REDIS_URL,
        decode_responses=True,
    )
    key = stream_key(thread_id)
    queue: asyncio.Queue[str] = asyncio.Queue()

    # Start reading from the newest entry at subscription time ($).
    # Tokens published before the SSE client connected are not replayed here;
    # only tokens published after the stream is open are forwarded.
    last_id = "$"

    logger.debug("[subscriber.read_stream] subscribed key=%s", key)

    async def _pump() -> None:
        """Background task — relay Stream entries onto the queue."""
        nonlocal last_id
        msg_count = 0
        try:
            while True:
                results = await client.xread({key: last_id}, block=_BLOCK_MS, count=100)
                if not results:
                    continue  # timeout — loop again (allows clean cancellation)
                batch_size = 0
                for _stream_key, entries in results:
                    for entry_id, fields in entries:
                        last_id = entry_id
                        raw: str = fields.get("data", "{}")
                        queue.put_nowait(raw)
                        msg_count += 1
                        batch_size += 1
                        if msg_count == 1:
                            try:
                                parsed = json.loads(raw)
                                logger.debug(
                                    "[subscriber._pump] first_token event=%s key=%s queue_size=%d",
                                    parsed.get("event", "?"),
                                    key,
                                    queue.qsize(),
                                )
                            except Exception:  # noqa: BLE001
                                logger.debug(
                                    "[subscriber._pump] first_token key=%s queue_size=%d",
                                    key,
                                    queue.qsize(),
                                )
                _track_xread(batch_size)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("[subscriber._pump] error key=%s: %s", key, exc)

    pump_task: asyncio.Task[None] = asyncio.create_task(_pump())

    try:
        yield queue
    finally:
        pump_task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(pump_task), timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001
            pass
        logger.debug("[subscriber.read_stream] unsubscribed key=%s", key)
