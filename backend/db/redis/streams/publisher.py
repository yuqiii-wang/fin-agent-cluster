"""backend.db.redis.streams.publisher -- Centrifugo Redis-Stream token publisher.

Each LLM token (or batch of tokens) is written to the ``fin:llm:tokens`` Redis
Stream on the shard that owns the thread.  Centrifugo's built-in Redis Stream
consumer picks it up and forwards the publication to the ``thread:{thread_id}``
WebSocket channel in real-time.

Shard routing
-------------
``SHA-256(thread_id) % len(DATABASE_REDIS_NODES)`` -- identical to the formula
used by :func:`~backend.centrifugo_mq.client.get_shard_index` so the Redis node
selected here always matches the Centrifugo token-stream node that subscribes
to it.

Wire format (one Redis Stream entry per Centrifugo publication)::

    XADD fin:llm:tokens * method publish payload '{"channel":"thread:<id>","data":{...}}'

Public API
----------
:func:`stream_token`       -- publish a single message (e.g. ``stream_end``).
:func:`stream_token_batch` -- publish many messages in one Redis pipeline round-trip.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Redis Stream key -- same name on every shard; routing is per-Redis-server.
_STREAM_NAME = "fin:llm:tokens"

# Module-level set to detect the first publish per thread (for INFO log).
_seen_threads: set[str] = set()


def _shard_index(thread_id: str) -> int:
    """Deterministic Redis shard index for *thread_id*.

    Mirrors the SHA-256 modulo routing used by Centrifugo token-stream nodes.
    """
    from backend.config import get_settings
    n = len(get_settings().DATABASE_REDIS_NODES) or 1
    return int(hashlib.sha256(thread_id.encode()).hexdigest(), 16) % n


def _encode_entry(channel: str, data: dict[str, Any]) -> dict[str, str]:
    """Return a single Redis Stream entry dict in Centrifugo publish format."""
    return {
        "method": "publish",
        "payload": json.dumps({"channel": channel, "data": data}, ensure_ascii=False),
    }


async def stream_token(thread_id: str, payload: dict[str, Any]) -> None:
    """Publish a single message to the Centrifugo Redis Stream.

    Suitable for low-frequency events such as ``stream_end``.  For bulk token
    delivery prefer :func:`stream_token_batch` to amortise round-trip overhead.

    Args:
        thread_id: LangGraph thread UUID -- determines the Redis shard.
        payload:   Arbitrary dict that becomes ``data`` in the Centrifugo
                   publication (e.g. ``{"event": "stream_end", ...}``).
    """
    from backend.db.redis import get_client

    shard = _shard_index(thread_id)
    client = await get_client(shard)
    channel = f"thread:{thread_id}"
    entry = _encode_entry(channel, payload)

    first = thread_id not in _seen_threads
    if first:
        _seen_threads.add(thread_id)

    await client.xadd(_STREAM_NAME, entry)

    if first:
        logger.info(
            "[stream_token] first xadd thread_id=%s stream=%s entry_keys=%s",
            thread_id, _STREAM_NAME, list(entry.keys()),
        )


async def stream_token_batch(thread_id: str, payloads: list[dict[str, Any]]) -> None:
    """Publish *payloads* to the Centrifugo Redis Stream in a single pipeline.

    All entries share the same shard and channel derived from *thread_id*.
    Using a pipeline reduces per-batch round-trips to one, regardless of how
    many tokens are in the batch.

    Args:
        thread_id: LangGraph thread UUID -- determines the Redis shard.
        payloads:  Ordered list of message dicts; each becomes one Redis Stream
                   entry and one Centrifugo publication.  Sequence integrity is
                   guaranteed by the ``seq`` field embedded in each payload by
                   the caller.
    """
    if not payloads:
        return

    from backend.db.redis import get_client

    shard = _shard_index(thread_id)
    client = await get_client(shard)
    channel = f"thread:{thread_id}"

    first = thread_id not in _seen_threads
    if first:
        _seen_threads.add(thread_id)

    pipe = client.pipeline(transaction=False)
    for payload in payloads:
        pipe.xadd(_STREAM_NAME, _encode_entry(channel, payload))
    await pipe.execute()

    if first:
        entry = _encode_entry(channel, payloads[0])
        logger.info(
            "[stream_token] first xadd thread_id=%s stream=%s entry_keys=%s",
            thread_id, _STREAM_NAME, list(entry.keys()),
        )

    logger.debug(
        "[stream_token_batch] thread_id=%s shard=%d published=%d",
        thread_id, shard, len(payloads),
    )


__all__ = ["stream_token", "stream_token_batch"]
