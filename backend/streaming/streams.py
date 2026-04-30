"""Redis Streams async client — persistent MQ/buffer for LLM events.

Two active streams:
  ``fin:llm:tokens``      — per-token events, shard-routed (redis-0 / redis-1),
                            consumed by Centrifugo native consumer (no XDEL).
  ``fin:llm:completions`` — one record per LLM call on redis-0 (shard 0),
                            consumed by the ``pg-persist`` Celery beat worker
                            which persists to ``fin_agents.llm_responses``
                            and then calls XDEL.

The module exposes:
  - ``xadd`` / ``xread`` / ``xread_group`` / ``xack`` / ``xdel`` — shard-0 ops
  - ``xadd_sharded`` — routes XADD to the correct Redis shard for a thread_id
    (used for ``fin:llm:tokens`` which is shard-routed to match Centrifugo)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import date, datetime
from typing import Any

import redis.asyncio as aioredis

from backend.config import get_settings
from backend.streaming.config import ALL_TOPICS, LLM_COMPLETIONS, STREAM_LLM_TOKENS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stream name / consumer group constants — derived from config
# ---------------------------------------------------------------------------

STREAM_LLM_COMPLETIONS: str = LLM_COMPLETIONS.stream_key
STREAM_TOKEN: str = STREAM_LLM_TOKENS
GROUP_CELERY_INGEST: str = LLM_COMPLETIONS.consumer_group

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

# Per-shard clients for xadd_sharded — keyed by (shard_index, loop_id).
_shard_clients: dict[tuple[int, int], aioredis.Redis] = {}


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


def _shard_index(thread_id: str) -> int:
    """Return the Redis shard index for *thread_id* using SHA-256 modulo routing.

    Matches the formula in :func:`~backend.centrifugo.client.get_shard_index`
    and :class:`~backend.db.redis.router.RedisRouter._shard_index` so tokens
    always land on the same Redis node that backs the corresponding Centrifugo
    node.

    Args:
        thread_id: LangGraph UUID string.

    Returns:
        Integer shard index (0 or 1, or 0 if only one node is configured).
    """
    settings = get_settings()
    urls = settings.DATABASE_REDIS_NODES or [settings.DATABASE_REDIS_URL]
    n = len(urls) or 1
    digest = int(hashlib.sha256(thread_id.encode()).hexdigest(), 16)
    return digest % n


async def _get_shard_client(shard: int) -> aioredis.Redis:
    """Return (or lazily create) a Redis client for *shard*.

    Clients are keyed by ``(shard, loop_id)`` so each ``asyncio.run()``
    call in a Celery worker gets a fresh pool bound to the current loop.

    Args:
        shard: Shard index (0 or 1).

    Returns:
        A ``redis.asyncio.Redis`` instance for the requested shard.
    """
    current_loop_id = id(asyncio.get_running_loop())
    key = (shard, current_loop_id)

    # Evict stale clients from previous event loops.
    stale = [k for k in list(_shard_clients) if k[1] != current_loop_id]
    for k in stale:
        try:
            await _shard_clients[k].aclose()
        except Exception:
            pass
        _shard_clients.pop(k, None)

    if key not in _shard_clients:
        settings = get_settings()
        urls = settings.DATABASE_REDIS_NODES or [settings.DATABASE_REDIS_URL]
        url = urls[shard] if shard < len(urls) else urls[0]
        _shard_clients[key] = aioredis.from_url(url, decode_responses=True)

    return _shard_clients[key]


async def xadd_sharded(
    thread_id: str,
    stream: str,
    payload: dict[str, Any],
    maxlen: int | None = None,
) -> str:
    """Append *payload* to *stream* on the shard Redis that owns *thread_id*.

    Routes the XADD to the correct Redis node using the same SHA-256 modulo
    formula as the Centrifugo and Redis router so that token events land on
    the Redis instance backing the right Centrifugo node for this thread.

    Args:
        thread_id: LangGraph thread UUID used for shard routing.
        stream:    Stream name (e.g. ``STREAM_TOKEN``).
        payload:   Dict to publish.  Values are coerced to strings.
        maxlen:    Soft cap on stream length (MAXLEN ~).

    Returns:
        Redis message ID string.
    """
    shard = _shard_index(thread_id)
    client = await _get_shard_client(shard)
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


async def xdel(stream: str, *msg_ids: str) -> int:
    """Delete *msg_ids* entries from *stream*.

    Called after a message has been persisted to PostgreSQL and acknowledged
    in its consumer group — the Redis entry is no longer needed.

    Args:
        stream:  Stream name.
        msg_ids: One or more message IDs to remove.

    Returns:
        Number of messages actually deleted.
    """
    if not msg_ids:
        return 0
    client = await _get_client()
    return await client.xdel(stream, *msg_ids)


async def xlen(stream: str) -> int:
    """Return the current number of entries in *stream*.

    Args:
        stream: Stream name.

    Returns:
        Entry count (0 if the stream does not exist).
    """
    client = await _get_client()
    return await client.xlen(stream)
