"""Rendezvous coordinator for concurrent stream ingest batches.

Each concurrency test run (identified by ``run_id``) registers N streams
independently across up to 4 FastAPI instances.  Exactly one instance wins
the coordinator lock (Redis SETNX) and spawns a long-lived ``asyncio.Task``
that:

1. Waits ``RENDEZVOUS_WINDOW_SECS`` for the first wave of streams.
2. Reads every stream config from Redis and dispatches ``run_fanout_batch``
   Celery tasks.
3. Keeps polling for **late joiners** every ``LATE_JOIN_INTERVAL_SECS`` for
   the full BLPOP window (``timeout_secs * 3 + 60 s``).  Streams whose
   browser requests were queued minutes after the initial batch are picked up
   here and dispatched in separate fanout tasks with the same timeout.
4. Exits when the BLPOP window expires.

The fanout Celery task in :mod:`backend.streaming.workers.fanout` then drives
all stream coroutines simultaneously and pushes each stream's result to its
own ``done_key`` Redis list as it completes.  Each FastAPI handler BLPOPs its
per-stream ``done_key`` and returns the final ``(produced, stop_reason,
ingest_ms)`` tuple to the caller.

Why one fanout task instead of a polling coordinator
-----------------------------------------------------
* **Truly simultaneous**: ``asyncio.gather()`` in one event loop starts all
  N coroutines at the same instant.  No alternating 2-second slices, no
  starvation when N > worker_count.
* **Late-joiner safety**: the coordinator stays alive for the full BLPOP
  window so browser-queued requests arriving minutes late still get
  dispatched rather than BLPOP-timing-out with 0 tokens.

Multiple FastAPI instances
--------------------------
Kong round-robins queries to 4 runner instances.  Streams in the same
``run_id`` may arrive at different instances.  The coordinator lock is in
Redis (SETNX); only the first instance wins and spawns the rendezvous task.
The rest simply register their stream and BLPOP for the result.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from backend.graph.agents.mock_perf.errors import SCHED_STREAM_STATE_MISSING

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Coordinator constants
# ---------------------------------------------------------------------------

#: Wait this long for all streams to register before dispatching the fanout.
RENDEZVOUS_WINDOW_SECS: float = 2.0

#: After the initial dispatch, poll Redis every this many seconds for late joiners.
LATE_JOIN_INTERVAL_SECS: float = 1.0

#: Multiplier applied to timeout_secs to compute the coordinator's max lifetime.
_DISPATCH_WINDOW_MULTIPLIER: float = 3.0

#: BLPOP prefix for final stream results.
_DONE_KEY_PREFIX: str = "fin:stream:ingest:done:"

#: TTL for done_key Redis entries pushed by the coordinator safety net.
_DONE_KEY_TTL_SECS: int = 120

#: Extra BLPOP deadline buffer beyond ``timeout_secs``.
_BLPOP_BUFFER_SECS: int = 60

#: Maximum streams per fanout Celery task.
MAX_STREAMS_PER_FANOUT_TASK: int = 2000


# ---------------------------------------------------------------------------
# Dispatcher entry point  (called by ``run_concurrency_task`` for each stream)
# ---------------------------------------------------------------------------


async def dispatch_scheduled_ingest(
    run_id: str,
    thread_id: str,
    stream_id: str,
    node_id: str,
    task_id: str,
    pub_task_id: str,
    task_name: str,
    token_per_sec: int,
    timeout_secs: float,
) -> tuple[int, str, int]:
    """Register a stream for fanout coordination and wait for its result.

    Args:
        run_id:         Shared run UUID.
        thread_id:      LangGraph thread UUID.
        stream_id:      Per-stream Celery ingest UUID.
        node_id:        Node execution UUID.
        task_id:      Task invocation UUID.
        pub_task_id:  Pre-created ``fin_agents.tasks`` row UUID (PK).
        task_name:       Full dot-separated task key.
        token_per_sec:  Target publish rate.
        timeout_secs:   Hard stream deadline.

    Returns:
        Tuple ``(produced, stop_reason, ingest_ms)``.
    """
    from backend.db.redis.session.stream_sched import (  # noqa: PLC0415
        register_stream as sched_register,
        try_become_coordinator,
    )
    from backend.db.redis.router import get_redis_router  # noqa: PLC0415
    from backend.streaming.streams import _shard_index  # noqa: PLC0415

    done_key = f"{_DONE_KEY_PREFIX}{stream_id}"
    shard_index = _shard_index(thread_id)

    await sched_register(
        run_id=run_id,
        stream_id=stream_id,
        thread_id=thread_id,
        node_id=node_id,
        task_id=task_id,
        pub_task_id=pub_task_id,
        task_name=task_name,
        token_per_sec=token_per_sec,
        timeout_secs=timeout_secs,
        shard_index=shard_index,
        done_key=done_key,
    )

    is_coordinator = await try_become_coordinator(run_id)
    if is_coordinator:
        asyncio.create_task(
            _run_rendezvous_and_dispatch(run_id, timeout_secs),
            name=f"sched-rendezvous-{run_id[:8]}",
        )
        logger.info(
            "[sched_coord] coordinator acquired run_id=%s timeout_secs=%.1f",
            run_id, timeout_secs,
        )

    # BLPOP deadline: 3x timeout + buffer covers rendezvous + queue wait + run.
    blpop_timeout = int(timeout_secs * 3) + _BLPOP_BUFFER_SECS
    client = get_redis_router().get_client_for_stream(stream_id)
    blpop_result = await client.blpop(done_key, timeout=blpop_timeout)

    if blpop_result is None:
        raise RuntimeError(
            f"[SCHED_COORDINATOR_TIMEOUT] fanout never signalled done "
            f"stream_id={stream_id} run_id={run_id} after {blpop_timeout}s"
        )

    _, result_json = blpop_result
    result: dict[str, Any] = json.loads(result_json)
    return (
        int(result.get("produced", 0)),
        str(result.get("stop_reason", "timeout")),
        int(result.get("ingest_ms", 0)),
    )


# ---------------------------------------------------------------------------
# Coordinator task  (runs once per run_id, exits after dispatching fanout)
# ---------------------------------------------------------------------------


async def _run_rendezvous_and_dispatch(run_id: str, timeout_secs: float) -> None:
    """Wait for stream registrations then dispatch fanout Celery task(s).

    Runs as a non-blocking ``asyncio.Task``.  Lifecycle:

    1. Sleeps ``RENDEZVOUS_WINDOW_SECS`` for the initial registrations.
    2. Dispatches a fanout for all registered streams.
    3. Enters a **late-joiner loop**: polls every ``LATE_JOIN_INTERVAL_SECS``
       for streams that registered after the window closed.
    4. Exits after ``timeout_secs * _DISPATCH_WINDOW_MULTIPLIER + _BLPOP_BUFFER_SECS``
       seconds total (matches the BLPOP deadline in dispatch_scheduled_ingest).

    Args:
        run_id:       Shared run UUID.
        timeout_secs: Hard deadline forwarded to each fanout task.
    """
    from backend.db.redis.session.stream_sched import (  # noqa: PLC0415
        get_run_stream_ids,
        get_all_stream_states,
    )
    from backend.streaming.workers.fanout import run_fanout_batch  # noqa: PLC0415

    t_coord_start = time.monotonic()
    logger.info(
        "[sched_coord] rendezvous window %.1fs run_id=%s",
        RENDEZVOUS_WINDOW_SECS, run_id,
    )
    await asyncio.sleep(RENDEZVOUS_WINDOW_SECS)

    dispatched_ids: set[str] = set()

    def _build_config(sid: str, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "stream_id": sid,
            "thread_id": state["thread_id"],
            "node_id": state["node_id"],
            "task_id": state["task_id"],
            "pub_task_id": state["pub_task_id"],
            "task_name": state["task_name"],
            "token_per_sec": state["token_per_sec"],
            "timeout_secs": state["timeout_secs"],
            "done_key": state["done_key"],
        }

    async def _dispatch_batch(new_ids: list[str], elapsed: float) -> None:
        """Fetch states for new_ids and dispatch fanout task(s)."""
        states = await get_all_stream_states(run_id, new_ids)
        configs: list[dict[str, Any]] = []
        skipped: list[str] = []
        for sid in new_ids:
            state = states.get(sid, {})
            if not state:
                logger.warning(
                    "[sched_coord] [%s] missing state stream_id=%s run_id=%s — pushing timeout result",
                    SCHED_STREAM_STATE_MISSING, sid, run_id,
                )
                skipped.append(sid)
                continue
            configs.append(_build_config(sid, state))

        if skipped:
            await _push_timeout_for_ids(run_id, skipped)

        if not configs:
            return
        chunks = [
            configs[i : i + MAX_STREAMS_PER_FANOUT_TASK]
            for i in range(0, len(configs), MAX_STREAMS_PER_FANOUT_TASK)
        ]
        for chunk in chunks:
            run_fanout_batch.delay(run_id, chunk, float(timeout_secs))
        dispatched_ids.update(cfg["stream_id"] for cfg in configs)
        logger.info(
            "[sched_coord] dispatched run_id=%s batch=%d skipped=%d total=%d tasks=%d elapsed=%.3fs",
            run_id, len(configs), len(skipped), len(dispatched_ids), len(chunks), elapsed,
        )
        for cfg in configs:
            reg_at = float(states.get(cfg["stream_id"], {}).get("registered_at", 0) or 0)
            logger.debug(
                "[sched_coord] stream_dispatched stream_id=%s task_id=%s run_id=%s registered_at=%.3f",
                cfg["stream_id"], cfg["task_id"], run_id, reg_at,
            )

    try:
        # -- Initial dispatch (after rendezvous window) -------------------------
        elapsed = time.monotonic() - t_coord_start
        stream_ids = await get_run_stream_ids(run_id)
        if not stream_ids:
            logger.warning("[sched_coord] no streams registered run_id=%s", run_id)
            return
        await _dispatch_batch(stream_ids, elapsed)

        if not dispatched_ids:
            logger.warning("[sched_coord] no valid configs run_id=%s", run_id)
            return

        # -- Late-joiner polling loop ------------------------------------------
        max_dispatch_window = timeout_secs * _DISPATCH_WINDOW_MULTIPLIER + _BLPOP_BUFFER_SECS
        while True:
            elapsed = time.monotonic() - t_coord_start
            if elapsed >= max_dispatch_window:
                logger.info(
                    "[sched_coord] coordinator done run_id=%s dispatched=%d elapsed=%.1fs",
                    run_id, len(dispatched_ids), elapsed,
                )
                break

            await asyncio.sleep(LATE_JOIN_INTERVAL_SECS)

            all_ids = await get_run_stream_ids(run_id)
            new_ids = [sid for sid in all_ids if sid not in dispatched_ids]
            if new_ids:
                elapsed = time.monotonic() - t_coord_start
                await _dispatch_batch(new_ids, elapsed)

    except Exception:
        logger.exception("[sched_coord] rendezvous failed run_id=%s", run_id)
        await _push_timeout_results(run_id)


async def _push_timeout_for_ids(
    run_id: str,
    stream_ids: list[str],
) -> None:
    """Push ``timeout`` done_keys for a specific list of stream_ids.

    Args:
        run_id:     Shared run UUID (for logging only).
        stream_ids: Stream IDs whose BLPOP must be unblocked.
    """
    from backend.db.redis.router import get_redis_router  # noqa: PLC0415

    router = get_redis_router()
    result_json = json.dumps({"produced": 0, "stop_reason": "timeout", "ingest_ms": 0})
    for sid in stream_ids:
        done_key = f"{_DONE_KEY_PREFIX}{sid}"
        try:
            client = router.get_client_for_stream(sid)
            await client.rpush(done_key, result_json)
            await client.expire(done_key, _DONE_KEY_TTL_SECS)
        except Exception:  # noqa: BLE001
            logger.warning(
                "[sched_coord] failed immediate timeout push done_key=%s stream_id=%s",
                done_key, sid,
            )


async def _push_timeout_results(run_id: str) -> None:
    """Push ``timeout`` results to all registered streams' done_keys.

    Called only when the coordinator itself fails before dispatching the fanout.

    Args:
        run_id: Shared run UUID.
    """
    from backend.db.redis.session.stream_sched import get_run_stream_ids  # noqa: PLC0415
    from backend.db.redis.router import get_redis_router  # noqa: PLC0415

    try:
        stream_ids = await get_run_stream_ids(run_id)
        router = get_redis_router()
        result_json = json.dumps({"produced": 0, "stop_reason": "timeout", "ingest_ms": 0})
        for sid in stream_ids:
            done_key = f"{_DONE_KEY_PREFIX}{sid}"
            try:
                client = router.get_client_for_stream(sid)
                await client.rpush(done_key, result_json)
                await client.expire(done_key, _DONE_KEY_TTL_SECS)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "[sched_coord] failed safety push done_key=%s stream_id=%s",
                    done_key, sid,
                )
        logger.warning(
            "[sched_coord] safety-net timeout pushed for %d streams run_id=%s",
            len(stream_ids), run_id,
        )
    except Exception:  # noqa: BLE001
        logger.exception("[sched_coord] safety-net push failed run_id=%s", run_id)


__all__ = ["dispatch_scheduled_ingest"]
