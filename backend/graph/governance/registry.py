"""Governance registry — live execution hierarchy tracked in Redis.

Tracks the three-level execution tree for every LangGraph run:

    thread_id  (top-level — LangGraph thread / user query)
      └─ node_id  (mid-level — LangGraph node execution)
           └─ stream_id  (leaf-level — Celery task / ingest run)

Any graph node that spawns long-running work (Celery tasks, background loops,
etc.) should register its leaf IDs here so that cancel and end handlers can
traverse the live hierarchy and emit clean terminal events to all in-flight
work without querying Postgres.

Redis keys
----------
* ``fin:gov:thread:{thread_id}:nodes`` — Set of active ``node_id`` values.
* ``fin:gov:node:{node_id}:streams``   — Set of active ``stream_id`` values.
* ``fin:gov:stream:{stream_id}``       — Hash ``{thread_id, node_id}``.

All keys carry a TTL matching the longest possible run (:data:`_GOV_TTL` = 2 h)
so orphaned entries self-clean even when deregister is skipped on crash.
"""

from __future__ import annotations

import logging

from backend.db.redis.router import get_redis_router

logger = logging.getLogger(__name__)

_GOV_TTL: int = 7_200  # 2 hours
_THREAD_NODES_PREFIX: str = "fin:gov:thread:"
_NODE_STREAMS_PREFIX: str = "fin:gov:node:"
_STREAM_META_PREFIX: str = "fin:gov:stream:"


def _thread_nodes_key(thread_id: str) -> str:
    return f"{_THREAD_NODES_PREFIX}{thread_id}:nodes"


def _node_streams_key(node_id: str) -> str:
    return f"{_NODE_STREAMS_PREFIX}{node_id}:streams"


def _stream_meta_key(stream_id: str) -> str:
    return f"{_STREAM_META_PREFIX}{stream_id}"


async def register_stream(
    thread_id: str,
    node_id: str,
    stream_id: str,
) -> None:
    """Register a new leaf stream under *node_id* / *thread_id*.

    Writes three Redis structures atomically via a pipeline:

    * Adds ``node_id`` to ``fin:gov:thread:{thread_id}:nodes``.
    * Adds ``stream_id`` to ``fin:gov:node:{node_id}:streams``.
    * Sets ``fin:gov:stream:{stream_id}`` hash with ``{thread_id, node_id}``.

    All keys are (re-)expired to :data:`_GOV_TTL` on each registration so a
    long-running session does not silently expire mid-flight.

    Args:
        thread_id: LangGraph thread UUID (top-level).
        node_id:   Node execution UUID (mid-level).
        stream_id: Leaf task UUID (e.g. Celery ingest run UUID).
    """
    router = get_redis_router()
    client = router.get_client_for_thread(thread_id)

    thread_nodes = _thread_nodes_key(thread_id)
    node_streams = _node_streams_key(node_id)
    stream_meta = _stream_meta_key(stream_id)

    pipe = client.pipeline()
    pipe.sadd(thread_nodes, node_id)
    pipe.expire(thread_nodes, _GOV_TTL)
    pipe.sadd(node_streams, stream_id)
    pipe.expire(node_streams, _GOV_TTL)
    pipe.hset(stream_meta, mapping={"thread_id": thread_id, "node_id": node_id})
    pipe.expire(stream_meta, _GOV_TTL)
    await pipe.execute()

    logger.debug(
        "[governance] registered thread_id=%s node_id=%s stream_id=%s",
        thread_id, node_id, stream_id,
    )


async def deregister_stream(
    thread_id: str,
    node_id: str,
    stream_id: str,
) -> None:
    """Remove a leaf stream from the governance hierarchy after it ends.

    Removes ``stream_id`` from the node set and deletes the stream meta hash.
    The node-to-thread link is left to expire naturally — the set will be
    empty and callers skip empty sets during traversal.

    Args:
        thread_id: LangGraph thread UUID (used for shard routing).
        node_id:   Node execution UUID.
        stream_id: Leaf task UUID.
    """
    router = get_redis_router()
    client = router.get_client_for_thread(thread_id)

    pipe = client.pipeline()
    pipe.srem(_node_streams_key(node_id), stream_id)
    pipe.delete(_stream_meta_key(stream_id))
    await pipe.execute()

    logger.debug(
        "[governance] deregistered thread_id=%s node_id=%s stream_id=%s",
        thread_id, node_id, stream_id,
    )


async def get_streams_for_node(
    thread_id: str,
    node_id: str,
) -> list[str]:
    """Return all live stream IDs registered under *node_id*.

    Args:
        thread_id: LangGraph thread UUID (used for shard routing).
        node_id:   Node execution UUID.

    Returns:
        List of ``stream_id`` strings currently registered under this node.
    """
    client = get_redis_router().get_client_for_thread(thread_id)
    members = await client.smembers(_node_streams_key(node_id))
    return [m.decode() if isinstance(m, bytes) else m for m in members]


async def get_streams_for_thread(thread_id: str) -> list[tuple[str, str]]:
    """Return all live ``(node_id, stream_id)`` pairs under *thread_id*.

    Traverses thread → nodes → streams.  Empty or missing node sets are
    silently skipped so a partial deregistration never causes key errors.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        List of ``(node_id, stream_id)`` tuples for all live leaf streams.
    """
    client = get_redis_router().get_client_for_thread(thread_id)
    raw_nodes = await client.smembers(_thread_nodes_key(thread_id))
    node_ids = [m.decode() if isinstance(m, bytes) else m for m in raw_nodes]

    result: list[tuple[str, str]] = []
    for node_id in node_ids:
        stream_ids = await get_streams_for_node(thread_id, node_id)
        for sid in stream_ids:
            result.append((node_id, sid))
    return result


__all__ = [
    "register_stream",
    "deregister_stream",
    "get_streams_for_node",
    "get_streams_for_thread",
]
