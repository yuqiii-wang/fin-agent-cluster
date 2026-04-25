"""PerfIngest Celery tasks — bulk token production for perf-test sessions.

Two tasks are registered on :data:`~backend.graph.agents.perf_test.celery_ingest.celery_app.perf_ingest_app`:

``bulk_ingest_stream``
    Writes one batch of mock tokens to ``fin:perf:{thread_id}`` via a Redis
    pipeline (fast sync XADD), then immediately **self-chains** another
    invocation for the same session until *total_tokens* are produced.

    This self-chaining is the **drain-first** strategy: a single worker
    stays focused on one session from start to completion before other
    sessions can be picked up.  No beat scheduling is needed for normal
    operation — the initial dispatch comes from
    :func:`~backend.graph.agents.perf_test.tasks.fanout_to_streams.run_ingest`.

``recover_stalled_streams``
    Beat-scheduled every :data:`~backend.graph.agents.perf_test.celery_ingest.config.PERF_INGEST_BEAT_INTERVAL`
    seconds.  Scans the ``fin:perf:ingest:active`` sorted set for sessions
    whose heartbeat timestamp is older than
    :data:`~backend.graph.agents.perf_test.celery_ingest.config.PERF_INGEST_STALL_THRESHOLD`
    seconds.  Picks **one** stalled session (oldest first) and redispatches
    ``bulk_ingest_stream`` for it — drain-first applies here too.

Completion signalling
---------------------
When all tokens are written the task:

1. Appends a sentinel entry to the stream so the pub reader knows to stop.
2. Updates the state hash to ``"completed"`` / ``"timeout"``.
3. Removes the session from the active set.

Timeout handling
----------------
Each batch checks whether ``time.time() - started_at > timeout_secs``.  On
expiry the task writes the sentinel + state update with
``stop_reason="timeout"`` and exits — no hardcoded sleep or grace period.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import redis.asyncio as aioredis

from backend.db.redis.router import get_redis_router
from backend.graph.agents.perf_test.celery_ingest.celery_app import perf_ingest_app
from backend.graph.agents.perf_test.celery_ingest.config import (
    PERF_INGEST_ACTIVE_SET_KEY,
    PERF_INGEST_BATCH_SIZE,
    PERF_INGEST_MAX_RETRIES,
    PERF_INGEST_RETRY_DELAY,
    PERF_INGEST_SENTINEL_FIELD,
    PERF_INGEST_SENTINEL_VALUE,
    PERF_INGEST_STALL_THRESHOLD,
    PERF_INGEST_STATE_KEY_PREFIX,
    PERF_INGEST_STREAM_MAXLEN,
    PERF_INGEST_STREAM_PREFIX,
)

logger = logging.getLogger(__name__)

_TASK_BULK_INGEST = "backend.graph.agents.perf_test.celery_ingest.tasks.bulk_ingest_stream"
_TASK_RECOVER = "backend.graph.agents.perf_test.celery_ingest.tasks.recover_stalled_streams"

# ---------------------------------------------------------------------------
# Per-task Redis client factory
# ---------------------------------------------------------------------------


def _make_clients(thread_id: str) -> tuple[aioredis.Redis, aioredis.Redis]:
    """Create per-task Redis clients routed by *thread_id*.

    Each Celery task runs inside its own ``asyncio.run()`` call so there is no
    benefit to caching clients across tasks.  Clients are created fresh each
    invocation and closed in a ``finally`` block.

    Returns a ``(thread_client, global_client)`` pair:

    * *thread_client* — connects to the shard determined by
      ``hash(thread_id) % node_count``.  Used for the per-session
      ``fin:perf:{thread_id}`` stream and ``fin:perf:ingest:state:{thread_id}``
      hash.
    * *global_client* — pinned to shard 0.  Used for the
      ``fin:perf:ingest:active`` sorted set, which is a global resource.

    When both clients resolve to the same URL a single
    ``aioredis.Redis`` instance is returned for both to avoid duplicate
    connection pools.

    Args:
        thread_id: LangGraph UUID identifying the session.

    Returns:
        ``(thread_client, global_client)`` tuple.
    """
    router = get_redis_router()
    thread_url = router.get_url_for_thread(thread_id)
    global_url = router.get_url_at(0)
    thread_client: aioredis.Redis = aioredis.from_url(thread_url, decode_responses=True)
    if thread_url == global_url:
        return thread_client, thread_client
    global_client: aioredis.Redis = aioredis.from_url(global_url, decode_responses=True)
    return thread_client, global_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stream_key(thread_id: str) -> str:
    """Return the per-session token stream key.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        Redis stream key, e.g. ``fin:perf:<uuid>``.
    """
    return f"{PERF_INGEST_STREAM_PREFIX}:{thread_id}"


def _state_key(thread_id: str) -> str:
    """Return the per-session ingest state hash key."""
    return f"{PERF_INGEST_STATE_KEY_PREFIX}:{thread_id}"


async def _signal_done(
    thread_client: aioredis.Redis,
    global_client: aioredis.Redis,
    thread_id: str,
    produced: int,
    stop_reason: str,
) -> None:
    """Write the end-of-stream sentinel and push a completion record.

    Args:
        thread_client: Redis client for the shard owning this thread's stream
                       and state-hash keys.
        global_client: Redis client for shard 0, which holds the global
                       ``fin:perf:ingest:active`` sorted set.
        thread_id:   LangGraph thread UUID.
        produced:    Total tokens written.
        stop_reason: ``"completed"`` or ``"timeout"``.
    """
    stream = _stream_key(thread_id)
    # Append sentinel so the pub reader terminates without polling.
    await thread_client.xadd(stream, {PERF_INGEST_SENTINEL_FIELD: PERF_INGEST_SENTINEL_VALUE})
    # Update state hash (thread-local shard).
    await thread_client.hset(
        _state_key(thread_id),
        mapping={"status": stop_reason, "produced": produced},
    )
    # Remove from active set — lives on shard 0 (global resource).
    await global_client.zrem(PERF_INGEST_ACTIVE_SET_KEY, thread_id)
    logger.info(
        "[perf_ingest] done produced=%d stop_reason=%s thread_id=%s",
        produced, stop_reason, thread_id,
    )


# ---------------------------------------------------------------------------
# Celery tasks
# ---------------------------------------------------------------------------


@perf_ingest_app.task(  # type: ignore[misc]
    name=_TASK_BULK_INGEST,
    bind=True,
    max_retries=PERF_INGEST_MAX_RETRIES,
    default_retry_delay=PERF_INGEST_RETRY_DELAY,
)
def bulk_ingest_stream(
    self: Any,
    thread_id: str,
    produced: int,
    total_tokens: int,
) -> dict[str, Any]:
    """Write one batch of mock tokens to ``fin:perf:{thread_id}``.

    Implements **drain-first** via self-chaining: on return it immediately
    re-dispatches itself for the same session until *total_tokens* are
    produced.  Only when the session is exhausted (or timed out) does
    chaining stop and the pub reader is unblocked.

    Args:
        thread_id:    LangGraph thread UUID.
        produced:     Tokens already written (0 on first call).
        total_tokens: Target token count for this session.

    Returns:
        Dict with ``produced`` and ``status``.
    """
    try:
        return asyncio.run(_run_batch(thread_id, produced, total_tokens))
    except Exception as exc:
        logger.warning("[perf_ingest.bulk] error thread_id=%s: %s", thread_id, exc)
        raise self.retry(exc=exc)


async def _run_batch(
    thread_id: str,
    produced: int,
    total_tokens: int,
) -> dict[str, Any]:
    """Inner async implementation of :func:`bulk_ingest_stream`.

    Args:
        thread_id:    LangGraph thread UUID.
        produced:     Tokens already written.
        total_tokens: Target token count.

    Returns:
        Dict with ``produced`` and ``status``.
    """
    thread_client, global_client = _make_clients(thread_id)
    try:
        state_raw = await thread_client.hgetall(_state_key(thread_id))

        # Timeout check (uses session start time stored during registration).
        started_at = float(state_raw.get("started_at", time.time()))
        timeout_secs = float(state_raw.get("timeout_secs", 60))
        if time.time() - started_at > timeout_secs:
            await _signal_done(thread_client, global_client, thread_id, produced, "timeout")
            return {"produced": produced, "status": "timeout"}

        batch_size = min(PERF_INGEST_BATCH_SIZE, total_tokens - produced)
        stream = _stream_key(thread_id)

        # Bulk write via pipeline — synchronous XADD, no per-entry round-trips.
        async with thread_client.pipeline(transaction=False) as pipe:
            for i in range(batch_size):
                seq = produced + i + 1
                pipe.xadd(
                    stream,
                    {"t": f"mock_msg_{thread_id}_{seq}"},
                    maxlen=PERF_INGEST_STREAM_MAXLEN,
                    approximate=True,
                )
            await pipe.execute()

        new_produced = produced + batch_size

        # Update heartbeat so the recovery beat can detect liveness.
        await thread_client.hset(
            _state_key(thread_id),
            mapping={"produced": new_produced, "heartbeat": time.time()},
        )
        # Active set is global — must go to shard 0.
        await global_client.zadd(PERF_INGEST_ACTIVE_SET_KEY, {thread_id: time.time()})

        logger.debug(
            "[perf_ingest.bulk] batch done produced=%d/%d thread_id=%s",
            new_produced, total_tokens, thread_id,
        )

        if new_produced >= total_tokens:
            await _signal_done(thread_client, global_client, thread_id, new_produced, "completed")
            return {"produced": new_produced, "status": "completed"}

        # Drain-first self-chain: same session, no delay.
        bulk_ingest_stream.apply_async(args=[thread_id, new_produced, total_tokens])
        return {"produced": new_produced, "status": "running"}
    finally:
        await thread_client.aclose()
        if global_client is not thread_client:
            await global_client.aclose()


@perf_ingest_app.task(  # type: ignore[misc]
    name=_TASK_RECOVER,
    bind=True,
    max_retries=1,
)
def recover_stalled_streams(self: Any) -> dict[str, int]:
    """Beat task — restart stalled ingest sessions.

    Scans ``fin:perf:ingest:active`` for sessions with a heartbeat older
    than :data:`~config.PERF_INGEST_STALL_THRESHOLD` seconds.  Picks the
    **single** oldest stalled session (drain-first: avoid spreading workers
    across multiple sessions simultaneously) and redispatches
    :func:`bulk_ingest_stream` for it.

    Returns:
        Dict with ``recovered`` count (0 or 1).
    """
    try:
        return asyncio.run(_recover())
    except Exception as exc:
        logger.warning("[perf_ingest.recover] error: %s", exc)
        raise self.retry(exc=exc)


async def _recover() -> dict[str, int]:
    """Inner async implementation of :func:`recover_stalled_streams`."""
    router = get_redis_router()
    # Active set is global — always on shard 0.
    global_client: aioredis.Redis = aioredis.from_url(
        router.get_url_at(0), decode_responses=True
    )
    try:
        stall_cutoff = time.time() - PERF_INGEST_STALL_THRESHOLD

        # Oldest-stall-first: ZRANGEBYSCORE ascending by heartbeat, limit=1.
        stalled: list[str] = await global_client.zrangebyscore(
            PERF_INGEST_ACTIVE_SET_KEY,
            "-inf",
            stall_cutoff,
            start=0,
            num=1,
        )
        if not stalled:
            return {"recovered": 0}

        thread_id = stalled[0]
        # State hash lives on the thread's own shard.
        thread_url = router.get_url_for_thread(thread_id)
        if thread_url == router.get_url_at(0):
            thread_client: aioredis.Redis = global_client
        else:
            thread_client = aioredis.from_url(thread_url, decode_responses=True)
        try:
            state = await thread_client.hgetall(_state_key(thread_id))

            if state.get("status") in ("completed", "timeout"):
                await global_client.zrem(PERF_INGEST_ACTIVE_SET_KEY, thread_id)
                return {"recovered": 0}

            produced = int(state.get("produced", 0))
            total_tokens = int(state.get("total_tokens", 0))

            if produced >= total_tokens:
                await global_client.zrem(PERF_INGEST_ACTIVE_SET_KEY, thread_id)
                return {"recovered": 0}

            logger.info(
                "[perf_ingest.recover] restarting stalled thread_id=%s produced=%d/%d",
                thread_id, produced, total_tokens,
            )
            bulk_ingest_stream.apply_async(args=[thread_id, produced, total_tokens])
            return {"recovered": 1}
        finally:
            if thread_client is not global_client:
                await thread_client.aclose()
    finally:
        await global_client.aclose()


__all__ = ["bulk_ingest_stream", "recover_stalled_streams"]
