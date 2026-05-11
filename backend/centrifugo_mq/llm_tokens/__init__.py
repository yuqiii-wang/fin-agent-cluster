"""centrifugo_mq.llm_tokens — LLM token streaming pipeline.

Architecture
------------
centrifugo-llm-{n} nodes consume LLM tokens directly from Redis Streams
(``fin:llm:tokens:{shard}``).  FastAPI writes each token via XADD so that
Centrifugo picks it up and pushes it to connected WebSocket subscribers.

In-process queues (``asyncio.Queue``) give the LangGraph stream callback a
non-blocking path; a lock per thread serialises concurrent flushes.

Usage::

    from backend.centrifugo_mq.llm_tokens import push_token, end_stream

    # inside an LLM streaming callback:
    await push_token(thread_id, node_id, token_text)

    # when the stream finishes:
    await end_stream(thread_id, node_id)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.centrifugo_mq.client import get_shard_index
from backend.config import get_settings
from backend.db.redis import get_client

logger = logging.getLogger(__name__)

_STREAM_PREFIX = "fin:llm:tokens"

# Per-thread in-process queue — non-blocking token intake for streaming callbacks.
_queues: dict[str, asyncio.Queue[str]] = {}

# Per-thread lock — serialises concurrent end_stream / flush calls.
_locks: dict[str, asyncio.Lock] = {}


def _get_queue(thread_id: str) -> asyncio.Queue[str]:
    if thread_id not in _queues:
        _queues[thread_id] = asyncio.Queue()
    return _queues[thread_id]


def _get_lock(thread_id: str) -> asyncio.Lock:
    if thread_id not in _locks:
        _locks[thread_id] = asyncio.Lock()
    return _locks[thread_id]


async def push_token(thread_id: str, node_id: str, token: str) -> None:
    """Write one LLM token to the Redis Stream and the in-process queue.

    centrifugo-llm-{shard} will pick up the XADD entry and push it to
    the frontend via WebSocket.  The in-process queue allows the caller to
    consume tokens locally without a round-trip.

    Errors are logged at WARNING level and never raised.

    Args:
        thread_id: LangGraph thread UUID; determines the shard.
        node_id:   Node that produced the token (for frontend routing).
        token:     Raw text fragment from the LLM stream.
    """
    shard = get_shard_index(thread_id)
    stream_key = f"{_STREAM_PREFIX}:{shard}"
    settings = get_settings()
    entry: dict[str, Any] = {
        "thread_id": thread_id,
        "node_id": node_id,
        "token": token,
    }
    try:
        redis = await get_client(shard)
        await redis.xadd(stream_key, entry, maxlen=settings.STREAM_MAX_LEN, approximate=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[llm_tokens] xadd failed shard=%d thread_id=%s: %s", shard, thread_id, exc)

    _get_queue(thread_id).put_nowait(token)


async def end_stream(thread_id: str, node_id: str) -> None:
    """Signal end-of-stream by writing a sentinel entry to the Redis Stream.

    The ``done=1`` sentinel tells Centrifugo consumers (and any local
    consumer of the in-process queue) that no more tokens will arrive
    for this thread/node pair.  In-process state is released afterwards.

    Args:
        thread_id: LangGraph thread UUID.
        node_id:   Node whose stream has finished.
    """
    shard = get_shard_index(thread_id)
    stream_key = f"{_STREAM_PREFIX}:{shard}"
    settings = get_settings()
    async with _get_lock(thread_id):
        try:
            redis = await get_client(shard)
            await redis.xadd(
                stream_key,
                {"thread_id": thread_id, "node_id": node_id, "token": "", "done": "1"},
                maxlen=settings.STREAM_MAX_LEN,
                approximate=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[llm_tokens] end_stream xadd failed shard=%d thread_id=%s: %s",
                shard, thread_id, exc,
            )
        finally:
            _queues.pop(thread_id, None)
            _locks.pop(thread_id, None)


__all__ = ["push_token", "end_stream"]
