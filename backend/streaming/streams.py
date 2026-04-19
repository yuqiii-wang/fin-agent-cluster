"""Redis Streams async client — persistent MQ/buffer for fin-trading events.

All stream I/O goes through a single connection-pool backed ``redis.asyncio.Redis``
instance.  The module exposes thin coroutine helpers so callers never manipulate
the raw ``aioredis`` API.

Stream / consumer-group naming convention
-----------------------------------------
Stream names use ``fin:<domain>:<topic>`` prefixes so Redis KEYS scanning and
ACL rules can target them independently of other keyspaces.

Consumer groups
---------------
Each stream topic has dedicated consumer groups for SSE delivery (low latency)
and Celery workers (durable processing).  Creating a group with ``ensure_group``
is idempotent — it silently ignores ``BUSYGROUP`` errors.

Configuration
-------------
Stream names, consumer groups, and related mappings are derived from
:mod:`backend.streaming.config` — the single source of truth for all topic
wiring.  Do not hardcode stream names or group names in this module.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime
from typing import Any

import redis.asyncio as aioredis

from backend.config import get_settings
from backend.streaming.config import ALL_TOPICS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stream name / consumer group constants — derived from config
# ---------------------------------------------------------------------------
# These aliases preserve the existing public API so external modules
# (resource_api, llm, api) do not need to change their imports.

STREAM_GRAPH_EVENTS: str = next(t.stream_key for t in ALL_TOPICS if t.human_key == "graph-events")
STREAM_MARKET_TICKS: str = next(t.stream_key for t in ALL_TOPICS if t.human_key == "market-ticks")
STREAM_TRADE_SIGNALS: str = next(t.stream_key for t in ALL_TOPICS if t.human_key == "trade-signals")
STREAM_NEWS_ENRICHED: str = next(t.stream_key for t in ALL_TOPICS if t.human_key == "news-enriched")
STREAM_LLM_COMPLETIONS: str = next(t.stream_key for t in ALL_TOPICS if t.human_key == "llm-completions")

GROUP_CELERY_GRAPH: str = next(t.consumer_group for t in ALL_TOPICS if t.human_key == "graph-events")
GROUP_CELERY_MARKET: str = next(t.consumer_group for t in ALL_TOPICS if t.human_key == "market-ticks")
GROUP_CELERY_SIGNALS: str = next(t.consumer_group for t in ALL_TOPICS if t.human_key == "trade-signals")
GROUP_CELERY_NEWS: str = next(t.consumer_group for t in ALL_TOPICS if t.human_key == "news-enriched")
GROUP_CELERY_LLM: str = next(t.consumer_group for t in ALL_TOPICS if t.human_key == "llm-completions")

#: stream → consumer groups to create at startup (built from config).
STREAM_CONSUMER_GROUPS: dict[str, list[str]] = {
    t.stream_key: [t.consumer_group] for t in ALL_TOPICS
}

#: Human-readable API key → internal stream name (built from config).
STREAM_KEY_MAP: dict[str, str] = {
    t.human_key: t.stream_key for t in ALL_TOPICS
}

_client: aioredis.Redis | None = None
_client_loop_id: int | None = None


def _json_default(obj: Any) -> str:
    """JSON serializer for types not handled by the default encoder."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)


def _to_fields(payload: dict[str, Any]) -> dict[str, str]:
    """Flatten a nested dict into a flat ``{field: str_value}`` map for XADD.

    Redis Streams require every field value to be a string.  Nested structures
    are JSON-encoded and scalars are cast with ``str()``.

    Args:
        payload: Arbitrary dict, possibly nested.

    Returns:
        Flat dict with all values as strings.
    """

    def _enc(v: Any) -> str:
        if isinstance(v, (datetime, date)):
            return v.isoformat()
        if isinstance(v, (dict, list, tuple)):
            return json.dumps(v, default=_json_default)
        if v is None:
            return ""
        return str(v)

    return {k: _enc(v) for k, v in payload.items()}


async def _get_client() -> aioredis.Redis:
    """Return (or lazily create) the shared stream Redis client.

    The client is recreated whenever the running event loop changes (e.g.
    each ``asyncio.run()`` call from a Celery worker) to avoid
    "Event loop is closed" errors caused by reusing a connection pool that
    was bound to a previous, already-closed loop.

    Returns:
        A ``redis.asyncio.Redis`` instance backed by a connection pool.
    """
    global _client, _client_loop_id
    current_loop_id = id(asyncio.get_running_loop())
    if _client is not None and _client_loop_id != current_loop_id:
        try:
            await _client.aclose()
        except Exception:
            pass
        _client = None
        _client_loop_id = None
    if _client is None:
        settings = get_settings()
        _client = aioredis.from_url(
            settings.DATABASE_REDIS_URL,
            decode_responses=True,
        )
        _client_loop_id = current_loop_id
    return _client


# ---------------------------------------------------------------------------
# Public stream operations
# ---------------------------------------------------------------------------


async def xadd(
    stream: str,
    payload: dict[str, Any],
    maxlen: int | None = None,
) -> str:
    """Append *payload* to *stream* and return the assigned message ID.

    Args:
        stream:  Stream name, e.g. ``STREAM_GRAPH_EVENTS``.
        payload: Dict to publish.  Values are coerced to strings.
        maxlen:  Soft cap on stream length (MAXLEN ~).  Defaults to
                 ``settings.STREAM_MAX_LEN``.

    Returns:
        Redis message ID string (e.g. ``'1713452341234-0'``).
    """
    client = await _get_client()
    if maxlen is None:
        maxlen = get_settings().STREAM_MAX_LEN
    fields = _to_fields(payload)
    msg_id: str = await client.xadd(stream, fields, maxlen=maxlen, approximate=True)
    return msg_id


async def xread(
    stream: str,
    last_id: str = "$",
    count: int = 100,
    block_ms: int = 0,
) -> list[tuple[str, dict[str, str]]]:
    """Read new messages from *stream* starting after *last_id*.

    Args:
        stream:   Stream name.
        last_id:  Exclusive lower bound message ID.  Use ``'$'`` for only
                  new messages, ``'0'`` to replay from the beginning.
        count:    Maximum messages to return.
        block_ms: Milliseconds to block waiting for new messages; 0 = no block.

    Returns:
        List of ``(message_id, fields_dict)`` pairs.
    """
    client = await _get_client()
    raw = await client.xread(
        {stream: last_id},
        count=count,
        block=block_ms if block_ms > 0 else None,
    )
    if not raw:
        return []
    _, messages = raw[0]
    return [(msg_id, fields) for msg_id, fields in messages]


async def ensure_group(stream: str, group: str) -> None:
    """Create *group* on *stream* if it does not already exist.

    Uses ID ``0`` so the group starts at the beginning of the stream on first
    creation, and creates the stream key if it does not exist (``mkstream``).

    Args:
        stream: Stream name.
        group:  Consumer group name.
    """
    client = await _get_client()
    try:
        await client.xgroup_create(stream, group, id="0", mkstream=True)
    except aioredis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def ensure_all_groups() -> None:
    """Create all default consumer groups for every known stream.

    Called at FastAPI startup to guarantee that Celery workers and the SSE
    gateway can immediately start consuming without racing on group creation.
    """
    for stream, groups in STREAM_CONSUMER_GROUPS.items():
        for group in groups:
            await ensure_group(stream, group)
    logger.info("[streaming.streams] all consumer groups ensured")


async def xread_group(
    stream: str,
    group: str,
    consumer: str,
    count: int = 50,
    block_ms: int = 1000,
    pending: bool = False,
) -> list[tuple[str, dict[str, str]]]:
    """Read messages from *stream* as member *consumer* of *group*.

    Args:
        stream:    Stream name.
        group:     Consumer group name.
        consumer:  Unique consumer name within the group.
        count:     Maximum messages per call.
        block_ms:  Milliseconds to block; 0 = no block.
        pending:   When ``True`` re-deliver pending (unacknowledged) messages
                   for this consumer (uses start ID ``'0'`` instead of ``'>'``).

    Returns:
        List of ``(message_id, fields_dict)`` pairs.
    """
    client = await _get_client()
    start = "0" if pending else ">"
    raw = await client.xreadgroup(
        groupname=group,
        consumername=consumer,
        streams={stream: start},
        count=count,
        block=block_ms if block_ms > 0 else None,
    )
    if not raw:
        return []
    _, messages = raw[0]
    return [(msg_id, fields) for msg_id, fields in messages]


async def xack(stream: str, group: str, *msg_ids: str) -> int:
    """Acknowledge *msg_ids* in consumer group *group* on *stream*.

    Args:
        stream:  Stream name.
        group:   Consumer group name.
        msg_ids: One or more message IDs returned by :func:`xread_group`.

    Returns:
        Number of messages successfully acknowledged.
    """
    if not msg_ids:
        return 0
    client = await _get_client()
    return await client.xack(stream, group, *msg_ids)


async def xlen(stream: str) -> int:
    """Return the current number of entries in *stream*.

    Args:
        stream: Stream name.

    Returns:
        Entry count (0 if the stream does not exist).
    """
    client = await _get_client()
    return await client.xlen(stream)
