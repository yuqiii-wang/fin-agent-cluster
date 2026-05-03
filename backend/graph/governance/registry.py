"""Governance registry — live execution hierarchy tracked in Redis.

Tracks the four-level execution tree for every LangGraph run:

    thread_id  (top-level — LangGraph thread / user query)
      └─ node_id   (LangGraph node execution)
           └─ task_id  (task invocation within the node)
                └─ stream_id  (optional LLM token stream)

Any graph node that spawns long-running work (Celery tasks, background loops,
etc.) should register its leaf IDs here so that cancel and end handlers can
traverse the live hierarchy and emit clean terminal events to all in-flight
work without querying Postgres.

Redis keys
----------
Hierarchy sets:
* ``fin:gov:thread:{thread_id}:nodes``    — Set of active ``node_id`` values.
* ``fin:gov:node:{node_id}:tasks``        — Set of active ``task_id`` values.
* ``fin:gov:task:{task_id}:streams``    — Set of active ``stream_id`` values.
* ``fin:gov:stream:{stream_id}``          — Hash ``{thread_id, node_id, task_id}``.

Per-level status (inherits from parent when not explicitly set):
* ``fin:gov:thread:{thread_id}:status``   — Hash ``{status, updated_at}``.
* ``fin:gov:node:{node_id}:status``       — Hash ``{status, thread_id, node_name}``.
* ``fin:gov:task:{task_id}:status``     — Hash ``{status, node_id, task_name}``.

Cancel signals (presence = cancel requested for that scope):
* ``fin:gov:node:{node_id}:cancel``       — String key; set when node cancel requested.
* ``fin:gov:task:{task_id}:cancel``     — String key; set when task cancel requested.

All keys carry a TTL matching the longest possible run (:data:`_GOV_TTL` = 2 h)
so orphaned entries self-clean even when deregister is skipped on crash.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from backend.db.redis.router import get_redis_router

logger = logging.getLogger(__name__)

_GOV_TTL: int = 7_200  # 2 hours
_THREAD_NODES_PREFIX: str = "fin:gov:thread:"
_NODE_TASKS_PREFIX: str = "fin:gov:node:"
_TASK_STREAMS_PREFIX: str = "fin:gov:task:"
_STREAM_META_PREFIX: str = "fin:gov:stream:"


def _thread_nodes_key(thread_id: str) -> str:
    return f"{_THREAD_NODES_PREFIX}{thread_id}:nodes"


def _node_tasks_key(node_id: str) -> str:
    return f"{_NODE_TASKS_PREFIX}{node_id}:tasks"


def _task_streams_key(task_id: str) -> str:
    return f"{_TASK_STREAMS_PREFIX}{task_id}:streams"


def _stream_meta_key(stream_id: str) -> str:
    return f"{_STREAM_META_PREFIX}{stream_id}"


# ── Per-level status keys ──────────────────────────────────────────────────


def _thread_status_key(thread_id: str) -> str:
    return f"fin:gov:thread:{thread_id}:status"


def _node_status_key(node_id: str) -> str:
    return f"fin:gov:node:{node_id}:status"


def _task_status_key(task_id: str) -> str:
    return f"fin:gov:task:{task_id}:status"


# ── Per-level cancel signal keys ───────────────────────────────────────────


def _node_cancel_key(node_id: str) -> str:
    return f"fin:gov:node:{node_id}:cancel"


def _task_cancel_key(task_id: str) -> str:
    return f"fin:gov:task:{task_id}:cancel"


async def register_stream(
    thread_id: str,
    node_id: str,
    task_id: str,
    stream_id: str,
) -> None:
    """Register a new leaf stream under *task_id* / *node_id* / *thread_id*.

    Writes four Redis structures atomically via a pipeline:

    * Adds ``node_id`` to ``fin:gov:thread:{thread_id}:nodes``.
    * Adds ``task_id`` to ``fin:gov:node:{node_id}:tasks``.
    * Adds ``stream_id`` to ``fin:gov:task:{task_id}:streams``.
    * Sets ``fin:gov:stream:{stream_id}`` hash with ``{thread_id, node_id, task_id}``.

    All keys are (re-)expired to :data:`_GOV_TTL` on each registration so a
    long-running session does not silently expire mid-flight.

    Args:
        thread_id:  LangGraph thread UUID (top-level).
        node_id:    Node execution UUID.
        task_id:  Task invocation UUID (task-level, between node and stream).
        stream_id:  Leaf stream UUID (e.g. Celery ingest run UUID).
    """
    router = get_redis_router()
    client = router.get_client_for_thread(thread_id)

    thread_nodes = _thread_nodes_key(thread_id)
    node_tasks = _node_tasks_key(node_id)
    task_streams = _task_streams_key(task_id)
    stream_meta = _stream_meta_key(stream_id)

    pipe = client.pipeline()
    pipe.sadd(thread_nodes, node_id)
    pipe.expire(thread_nodes, _GOV_TTL)
    pipe.sadd(node_tasks, task_id)
    pipe.expire(node_tasks, _GOV_TTL)
    pipe.sadd(task_streams, stream_id)
    pipe.expire(task_streams, _GOV_TTL)
    pipe.hset(stream_meta, mapping={"thread_id": thread_id, "node_id": node_id, "task_id": task_id})
    pipe.expire(stream_meta, _GOV_TTL)
    await pipe.execute()

    logger.debug(
        "[governance] registered thread_id=%s node_id=%s task_id=%s stream_id=%s",
        thread_id, node_id, task_id, stream_id,
    )


async def deregister_stream(
    thread_id: str,
    node_id: str,
    task_id: str,
    stream_id: str,
) -> None:
    """Remove a leaf stream from the governance hierarchy after it ends.

    Removes ``stream_id`` from the task set and deletes the stream meta hash.
    Upper-level links (node→tasks, thread→nodes) are left to expire naturally.

    Args:
        thread_id: LangGraph thread UUID (used for shard routing).
        node_id:   Node execution UUID.
        task_id: Task invocation UUID.
        stream_id: Leaf stream UUID.
    """
    router = get_redis_router()
    client = router.get_client_for_thread(thread_id)

    pipe = client.pipeline()
    pipe.srem(_task_streams_key(task_id), stream_id)
    pipe.delete(_stream_meta_key(stream_id))
    await pipe.execute()

    logger.debug(
        "[governance] deregistered thread_id=%s node_id=%s task_id=%s stream_id=%s",
        thread_id, node_id, task_id, stream_id,
    )


async def get_streams_for_task(
    thread_id: str,
    task_id: str,
) -> list[str]:
    """Return all live stream IDs registered under *task_id*.

    Args:
        thread_id: LangGraph thread UUID (used for shard routing).
        task_id: Task invocation UUID.

    Returns:
        List of ``stream_id`` strings currently registered under this task.
    """
    client = get_redis_router().get_client_for_thread(thread_id)
    members = await client.smembers(_task_streams_key(task_id))
    return [m.decode() if isinstance(m, bytes) else m for m in members]


async def get_tasks_for_node(
    thread_id: str,
    node_id: str,
) -> list[str]:
    """Return all live task UUIDs registered under *node_id*.

    Args:
        thread_id: LangGraph thread UUID (used for shard routing).
        node_id:   Node execution UUID.

    Returns:
        List of ``task_id`` strings currently registered under this node.
    """
    client = get_redis_router().get_client_for_thread(thread_id)
    members = await client.smembers(_node_tasks_key(node_id))
    return [m.decode() if isinstance(m, bytes) else m for m in members]


async def get_streams_for_thread(thread_id: str) -> list[tuple[str, str, str]]:
    """Return all live ``(node_id, task_id, stream_id)`` triples under *thread_id*.

    Traverses thread → nodes → tasks → streams.  Empty or missing sets are
    silently skipped so a partial deregistration never causes key errors.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        List of ``(node_id, task_id, stream_id)`` triples for all live streams.
    """
    client = get_redis_router().get_client_for_thread(thread_id)
    raw_nodes = await client.smembers(_thread_nodes_key(thread_id))
    node_ids = [m.decode() if isinstance(m, bytes) else m for m in raw_nodes]

    result: list[tuple[str, str, str]] = []
    for node_id in node_ids:
        task_ids = await get_tasks_for_node(thread_id, node_id)
        for task_id in task_ids:
            stream_ids = await get_streams_for_task(thread_id, task_id)
            for sid in stream_ids:
                result.append((node_id, task_id, sid))
    return result


# ── Per-level status management ────────────────────────────────────────────


async def set_thread_status(thread_id: str, status: str) -> None:
    """Persist the thread-level execution status to Redis.

    Args:
        thread_id: LangGraph thread UUID.
        status:    One of ``'running'``, ``'completed'``, ``'failed'``, ``'cancelled'``.
    """
    client = get_redis_router().get_client_for_thread(thread_id)
    key = _thread_status_key(thread_id)
    pipe = client.pipeline()
    pipe.hset(key, mapping={"status": status, "updated_at": datetime.now(timezone.utc).isoformat()})
    pipe.expire(key, _GOV_TTL)
    await pipe.execute()
    logger.debug("[governance] thread_status thread_id=%s status=%s", thread_id, status)


async def set_node_status(thread_id: str, node_id: str, status: str, node_name: str = "") -> None:
    """Persist the node-level execution status to Redis.

    Args:
        thread_id: LangGraph thread UUID (used for shard routing).
        node_id:   Node execution UUID.
        status:    One of ``'running'``, ``'completed'``, ``'failed'``, ``'cancelled'``.
        node_name: Human-readable node name for debugging (optional).
    """
    client = get_redis_router().get_client_for_thread(thread_id)
    key = _node_status_key(node_id)
    pipe = client.pipeline()
    pipe.hset(key, mapping={
        "status": status,
        "thread_id": thread_id,
        "node_name": node_name,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    pipe.expire(key, _GOV_TTL)
    await pipe.execute()
    logger.debug(
        "[governance] node_status node_id=%s node_name=%s status=%s thread_id=%s",
        node_id, node_name, status, thread_id,
    )


async def get_node_status(thread_id: str, node_id: str) -> str | None:
    """Return the effective node status, inheriting from parent thread if unset.

    Status inheritance order: node → thread.

    Args:
        thread_id: LangGraph thread UUID.
        node_id:   Node execution UUID.

    Returns:
        Status string or ``None`` when the node has not been registered.
    """
    client = get_redis_router().get_client_for_thread(thread_id)
    raw = await client.hgetall(_node_status_key(node_id))
    if raw:
        val = raw.get(b"status") or raw.get("status")
        return val.decode() if isinstance(val, bytes) else val
    # Fall back to thread status.
    thread_raw = await client.hgetall(_thread_status_key(thread_id))
    if thread_raw:
        val = thread_raw.get(b"status") or thread_raw.get("status")
        return val.decode() if isinstance(val, bytes) else val
    return None


async def set_task_status(
    thread_id: str,
    task_id: str,
    status: str,
    node_id: str = "",
    task_name: str = "",
) -> None:
    """Persist the task-level execution status to Redis.

    Args:
        thread_id: LangGraph thread UUID (used for shard routing).
        task_id: Task invocation UUID.
        status:    One of ``'running'``, ``'completed'``, ``'failed'``, ``'cancelled'``.
        node_id:   Parent node UUID (optional, for debugging).
        task_name:  Dot-separated task key (optional, for debugging).
    """
    client = get_redis_router().get_client_for_thread(thread_id)
    key = _task_status_key(task_id)
    pipe = client.pipeline()
    pipe.hset(key, mapping={
        "status": status,
        "node_id": node_id,
        "task_name": task_name,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    pipe.expire(key, _GOV_TTL)
    await pipe.execute()
    logger.debug(
        "[governance] task_status task_id=%s task_name=%s status=%s node_id=%s",
        task_id, task_name, status, node_id,
    )


async def get_task_status(thread_id: str, task_id: str) -> str | None:
    """Return the effective task status, inheriting from parent node/thread if unset.

    Status inheritance order: task → node → thread.

    Args:
        thread_id: LangGraph thread UUID.
        task_id: Task invocation UUID.

    Returns:
        Status string or ``None`` when the task has not been registered.
    """
    client = get_redis_router().get_client_for_thread(thread_id)
    raw = await client.hgetall(_task_status_key(task_id))
    if raw:
        val = raw.get(b"status") or raw.get("status")
        return val.decode() if isinstance(val, bytes) else val
    # Fall back to node, then thread.
    node_id_bytes = None
    # Try to find the node_id from the task set membership (scan nodes for thread).
    nodes_raw = await client.smembers(_thread_nodes_key(thread_id))
    for n in nodes_raw:
        nid = n.decode() if isinstance(n, bytes) else n
        tasks = await client.smembers(_node_tasks_key(nid))
        task_strs = [t.decode() if isinstance(t, bytes) else t for t in tasks]
        if task_id in task_strs:
            node_id_bytes = nid
            break
    if node_id_bytes:
        return await get_node_status(thread_id, node_id_bytes)
    return None


# ── Cancel signal management ───────────────────────────────────────────────


async def request_node_cancel(thread_id: str, node_id: str, node_name: str = "") -> None:
    """Set a cancel signal for a specific node and update its status to 'cancelled'.

    Nodes check this signal via :func:`check_node_cancel` before starting each
    sub-task and should raise ``asyncio.CancelledError`` when it is set.

    Args:
        thread_id: LangGraph thread UUID (used for shard routing).
        node_id:   Node execution UUID to cancel.
        node_name: Human-readable node name for debugging (optional).
    """
    client = get_redis_router().get_client_for_thread(thread_id)
    key = _node_cancel_key(node_id)
    pipe = client.pipeline()
    pipe.set(key, "1", ex=_GOV_TTL)
    await pipe.execute()
    await set_node_status(thread_id, node_id, "cancelled", node_name)
    logger.info(
        "[governance] node_cancel_requested node_id=%s node_name=%s thread_id=%s",
        node_id, node_name, thread_id,
    )


async def check_node_cancel(thread_id: str, node_id: str) -> bool:
    """Return ``True`` if a cancel signal is set for *node_id* or its parent thread.

    Checks both the node-level cancel key and the thread status so that
    thread-level cancellations propagate automatically to all nodes.

    Args:
        thread_id: LangGraph thread UUID.
        node_id:   Node execution UUID.
    """
    client = get_redis_router().get_client_for_thread(thread_id)
    node_cancel = await client.exists(_node_cancel_key(node_id))
    if node_cancel:
        return True
    # Inherit from thread status.
    thread_raw = await client.hgetall(_thread_status_key(thread_id))
    if thread_raw:
        val = thread_raw.get(b"status") or thread_raw.get("status")
        status = val.decode() if isinstance(val, bytes) else val
        return status == "cancelled"
    return False


async def request_task_cancel(
    thread_id: str,
    task_id: str,
    node_id: str = "",
    task_name: str = "",
) -> None:
    """Set a cancel signal for a specific task and update its status to 'cancelled'.

    Tasks check this signal via :func:`check_task_cancel` at yield points and
    should raise ``asyncio.CancelledError`` when it is set.

    Args:
        thread_id: LangGraph thread UUID (used for shard routing).
        task_id: Task invocation UUID to cancel.
        node_id:   Parent node UUID (used for inheritance lookups, optional).
        task_name:  Dot-separated task key for debugging (optional).
    """
    client = get_redis_router().get_client_for_thread(thread_id)
    key = _task_cancel_key(task_id)
    pipe = client.pipeline()
    pipe.set(key, "1", ex=_GOV_TTL)
    await pipe.execute()
    await set_task_status(thread_id, task_id, "cancelled", node_id, task_name)
    logger.info(
        "[governance] task_cancel_requested task_id=%s task_name=%s node_id=%s thread_id=%s",
        task_id, task_name, node_id, thread_id,
    )


async def check_task_cancel(thread_id: str, task_id: str, node_id: str = "") -> bool:
    """Return ``True`` if a cancel signal is set for *task_id*, its node, or thread.

    Checks in order: task cancel key → node cancel key → thread status.

    Args:
        thread_id: LangGraph thread UUID.
        task_id: Task invocation UUID.
        node_id:   Parent node UUID for node-level inheritance check.
    """
    client = get_redis_router().get_client_for_thread(thread_id)
    task_cancel = await client.exists(_task_cancel_key(task_id))
    if task_cancel:
        return True
    if node_id:
        return await check_node_cancel(thread_id, node_id)
    return False


async def close_governed_ids(thread_id: str) -> None:
    """Cascade-close all governed IDs registered under *thread_id*.

    Traverses the full hierarchy (thread → nodes → tasks → streams) and
    deletes every Redis key tracked under this thread so the registry is
    left clean after a terminal transition.

    Specifically removes, in leaf-to-root order:
    * Stream meta hashes (``fin:gov:stream:{stream_id}``).
    * Task-streams sets (``fin:gov:task:{task_id}:streams``).
    * Task status / cancel keys.
    * Node-tasks sets (``fin:gov:node:{node_id}:tasks``).
    * Node status / cancel keys.
    * Thread-nodes set (``fin:gov:thread:{thread_id}:nodes``).
    * Thread status key.

    Safe to call multiple times — missing keys are silently ignored.

    Args:
        thread_id: LangGraph thread UUID identifying the top-level scope.
    """
    client = get_redis_router().get_client_for_thread(thread_id)

    # Collect all node_ids registered under this thread.
    raw_nodes = await client.smembers(_thread_nodes_key(thread_id))
    node_ids = [m.decode() if isinstance(m, bytes) else m for m in raw_nodes]

    keys_to_delete: list[str] = []

    for node_id in node_ids:
        # Collect task_ids under this node.
        raw_tasks = await client.smembers(_node_tasks_key(node_id))
        task_ids = [m.decode() if isinstance(m, bytes) else m for m in raw_tasks]

        for task_id in task_ids:
            # Collect stream_ids under this task.
            raw_streams = await client.smembers(_task_streams_key(task_id))
            stream_ids = [m.decode() if isinstance(m, bytes) else m for m in raw_streams]

            for stream_id in stream_ids:
                keys_to_delete.append(_stream_meta_key(stream_id))

            # Task-level keys.
            keys_to_delete.append(_task_streams_key(task_id))
            keys_to_delete.append(_task_status_key(task_id))
            keys_to_delete.append(_task_cancel_key(task_id))

        # Node-level keys.
        keys_to_delete.append(_node_tasks_key(node_id))
        keys_to_delete.append(_node_status_key(node_id))
        keys_to_delete.append(_node_cancel_key(node_id))

    # Thread-level keys.
    keys_to_delete.append(_thread_nodes_key(thread_id))
    keys_to_delete.append(_thread_status_key(thread_id))

    if keys_to_delete:
        pipe = client.pipeline()
        for key in keys_to_delete:
            pipe.delete(key)
        await pipe.execute()

    logger.info(
        "[governance] close_governed_ids thread_id=%s nodes=%d keys_deleted=%d",
        thread_id,
        len(node_ids),
        len(keys_to_delete),
    )


__all__ = [
    "register_stream",
    "deregister_stream",
    "get_streams_for_task",
    "get_tasks_for_node",
    "get_streams_for_thread",
    # Per-level status
    "set_thread_status",
    "set_node_status",
    "get_node_status",
    "set_task_status",
    "get_task_status",
    # Cancel signals
    "request_node_cancel",
    "check_node_cancel",
    "request_task_cancel",
    "check_task_cancel",
    # Cascade close
    "close_governed_ids",
]

