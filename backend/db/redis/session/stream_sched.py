"""Redis state management for the concurrent stream fanout scheduler.

Tracks per-run stream registrations and provides the coordinator lock /
rendezvous helpers.  The fanout Celery task
(:mod:`backend.streaming.workers.fanout`) handles all per-stream progress
internally without writing back to Redis — only the registration (for
the rendezvous) and the coordinator lock are needed here.

Key schema
----------
``fin:stream:sched:state:{run_id}:{stream_id}``
    Hash — per-stream config registered before the fanout task starts.
    Fields: thread_id, node_id, pub_task_id, task_key, token_per_sec,
            timeout_secs, shard_index, done_key, registered_at.

``fin:stream:sched:coord:{run_id}``
    String with TTL — coordinator ownership lock; first registrant wins via
    SETNX.  TTL prevents a crashed coordinator from blocking the run forever.

``fin:stream:sched:streams:{run_id}``
    Set — all stream_ids registered for this run (coordinator reads via SMEMBERS
    after the rendezvous window).

All scheduler keys live on **shard 0** so the coordinator only needs a single
Redis connection.  The ``done_key`` for each stream is written by the fanout
task using the stream's own shard client so the dispatcher's BLPOP is routed
consistently.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from backend.db.redis.router import get_redis_router

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TTL constants
# ---------------------------------------------------------------------------

#: Coordinator lock TTL — covers the full test timeout plus a generous buffer.
_COORD_LOCK_TTL_SECS: int = 600  # 10 minutes

#: TTL for all other scheduler keys (run state, stream-id set).
_STATE_TTL_SECS: int = 3_600  # 1 hour

# ---------------------------------------------------------------------------
# Key helpers  (all on shard 0 — see module docstring)
# ---------------------------------------------------------------------------

_KEY_PREFIX: str = "fin:stream:sched"


def _state_key(run_id: str, stream_id: str) -> str:
    return f"{_KEY_PREFIX}:state:{run_id}:{stream_id}"


def _coord_key(run_id: str) -> str:
    return f"{_KEY_PREFIX}:coord:{run_id}"


def _streams_key(run_id: str) -> str:
    return f"{_KEY_PREFIX}:streams:{run_id}"


def _sched_client():
    """Return the Redis client for scheduler state (always shard 0)."""
    return get_redis_router().get_client_at(0)


# ---------------------------------------------------------------------------
# Stream registration
# ---------------------------------------------------------------------------


async def register_stream(
    run_id: str,
    stream_id: str,
    thread_id: str,
    node_id: str,
    pub_task_id: int,
    task_key: str,
    token_per_sec: int,
    timeout_secs: float,
    shard_index: int,
    done_key: str,
) -> None:
    """Register a stream in the run's scheduler registry.

    Called by ``dispatch_scheduled_ingest`` for each independent stream that
    belongs to the same test run.  After the rendezvous window the coordinator
    reads all registered configs and dispatches a single fanout Celery task.

    Args:
        run_id:        Shared run UUID (extracted from frontend query string).
        stream_id:     Per-stream UUID.
        thread_id:     LangGraph thread UUID.
        node_id:       Node execution UUID.
        pub_task_id:   Pre-created ``fin_agents.tasks`` row ID.
        task_key:      Full dot-separated Celery task key.
        token_per_sec: Target publish rate.
        timeout_secs:  Hard stream deadline.
        shard_index:   Redis shard for this stream's thread.
        done_key:      Redis list key the dispatcher BLPOPs for the final result.
    """
    client = _sched_client()
    state: dict[str, str] = {
        "thread_id": thread_id,
        "node_id": node_id,
        "pub_task_id": str(pub_task_id),
        "task_key": task_key,
        "token_per_sec": str(token_per_sec),
        "timeout_secs": str(timeout_secs),
        "shard_index": str(shard_index),
        "done_key": done_key,
        "registered_at": str(time.time()),
    }
    pipe = client.pipeline()
    pipe.hset(_state_key(run_id, stream_id), mapping=state)
    pipe.expire(_state_key(run_id, stream_id), _STATE_TTL_SECS)
    pipe.sadd(_streams_key(run_id), stream_id)
    pipe.expire(_streams_key(run_id), _STATE_TTL_SECS)
    await pipe.execute()
    logger.info(
        "[stream_sched] registered stream_id=%s run_id=%s t=%.3f",
        stream_id, run_id, time.time(),
    )


# ---------------------------------------------------------------------------
# State reads
# ---------------------------------------------------------------------------


async def get_run_stream_ids(run_id: str) -> list[str]:
    """Return all stream_ids registered for *run_id*.

    Args:
        run_id: Shared run UUID.

    Returns:
        List of stream_id strings (order not guaranteed).
    """
    client = _sched_client()
    result = await client.smembers(_streams_key(run_id))
    return list(result)


async def get_all_stream_states(
    run_id: str,
    stream_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Batch-read configs for all streams in one pipeline round-trip.

    Args:
        run_id:     Shared run UUID.
        stream_ids: List of stream_ids to fetch.

    Returns:
        Dict mapping stream_id -> config dict (missing ids map to ``{}``).
    """
    if not stream_ids:
        return {}
    client = _sched_client()
    pipe = client.pipeline()
    for sid in stream_ids:
        pipe.hgetall(_state_key(run_id, sid))
    results = await pipe.execute()
    out: dict[str, dict[str, Any]] = {}
    for sid, raw in zip(stream_ids, results):
        if not raw:
            out[sid] = {}
            continue
        out[sid] = {
            "thread_id": raw.get("thread_id", ""),
            "node_id": raw.get("node_id", ""),
            "pub_task_id": int(raw.get("pub_task_id", 0)),
            "task_key": raw.get("task_key", ""),
            "token_per_sec": int(raw.get("token_per_sec", 500)),
            "timeout_secs": float(raw.get("timeout_secs", 60)),
            "shard_index": int(raw.get("shard_index", 0)),
            "done_key": raw.get("done_key", ""),
            "registered_at": float(raw.get("registered_at", 0)),
        }
    return out


# ---------------------------------------------------------------------------
# Coordinator lock
# ---------------------------------------------------------------------------


async def try_become_coordinator(run_id: str) -> bool:
    """Attempt to claim the coordinator role for this run via Redis SETNX.

    Only the first FastAPI coroutine to call this for a given ``run_id``
    succeeds.  All other coroutines skip spawning the rendezvous task and
    only BLPOP for their stream's done result.

    Args:
        run_id: Shared run UUID.

    Returns:
        ``True`` if this caller is now the coordinator; ``False`` otherwise.
    """
    client = _sched_client()
    result = await client.set(
        _coord_key(run_id), "1", nx=True, ex=_COORD_LOCK_TTL_SECS
    )
    return result is not None


__all__ = [
    "register_stream",
    "get_run_stream_ids",
    "get_all_stream_states",
    "try_become_coordinator",
]
