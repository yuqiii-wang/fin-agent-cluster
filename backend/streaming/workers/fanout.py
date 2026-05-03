"""Celery worker — concurrent fanout ingest task for scheduler runs.

All streams in a ``run_id`` batch are executed **simultaneously** inside
a single ``asyncio.gather()`` call within one Celery task.  Because the
mock LLM is fully I/O-bound (``await asyncio.sleep()`` for rate-limiting,
``await xadd_sharded()`` for Redis writes), the event loop multiplexes N
concurrent streams without any prefork starvation.

Comparison with the old slice-based coordinator
-----------------------------------------------
Old design:
  * 1 Celery task per stream slice (2-second bursts).
  * FastAPI coordinator polling every 250 ms to re-dispatch.
  * Inflight keys + state counters in Redis.
  * With 8 workers and 10 streams, 2 streams always queued → starvation.

New design:
  * 1 Celery task for the entire ``run_id`` batch.
  * All N streams run in the same event loop via ``asyncio.gather()``.
  * No inflight keys, no state polling, no slice tracking.
  * Coordinator only needed for the 0.5-second rendezvous window.

Flow
----
1. FastAPI coordinator waits RENDEZVOUS_WINDOW_SECS for all streams to
   register, then dispatches ``run_fanout_batch.delay(run_id, configs)``.
2. This task starts all N ``_ingest_one`` coroutines concurrently.
3. Each coroutine runs the full-duration rate-limited mock LLM loop and
   pushes its result to its own ``done_key`` immediately on completion.
4. FastAPI handlers BLPOP their individual ``done_key`` — they are notified
   as soon as *their* stream finishes, without waiting for all N.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from typing import Any

from backend.streaming.celery_app import celery_app
from backend.streaming.streams import STREAM_TOKEN, xadd_sharded

logger = logging.getLogger(__name__)

#: Tokens per Redis XADD batch.
_FLUSH_SIZE: int = 100

#: Done-key Redis list TTL in seconds.
_DONE_KEY_TTL_SECS: int = 120

#: Extra grace period added on top of ``timeout_secs`` for the outer
#: ``asyncio.wait_for`` guard.  Keeps the event loop from running forever
#: if an ingest coroutine stalls (e.g., Redis back-pressure).
_WAIT_FOR_GRACE_SECS: int = 30

#: Maximum concurrent ``xadd_sharded`` calls inside one fanout task.
#: Prevents Redis connection exhaustion when running hundreds of streams
#: simultaneously — each stream tries to XADD at the same instant.
_XADD_CONCURRENCY: int = 100


# ---------------------------------------------------------------------------
# Celery task entry point
# ---------------------------------------------------------------------------


@celery_app.task(
    name="backend.streaming.workers.fanout.run_fanout_batch",
    bind=False,
    queue="stream:ingest",
    acks_late=True,
)
def run_fanout_batch(
    run_id: str,
    stream_configs: list[dict[str, Any]],
    timeout_secs: float,
) -> dict[str, Any]:
    """Run all streams in a ``run_id`` batch concurrently.

    All ``stream_configs`` are executed simultaneously inside a single
    ``asyncio.gather()`` in one Celery worker process.  Each coroutine
    pushes its result to its own ``done_key`` on completion.

    Args:
        run_id:         Shared run UUID.
        stream_configs: List of per-stream config dicts, each containing:
                        ``stream_id``, ``thread_id``, ``node_id``,
                        ``pub_task_id``, ``task_name``, ``token_per_sec``,
                        ``timeout_secs``, ``done_key``.
        timeout_secs:   Hard deadline for all streams in this batch.

    Returns:
        Dict mapping ``stream_id`` → result dict (for diagnostics; the
        primary result delivery is via per-stream ``done_key`` RPUSH).
    """
    logger.info(
        "[fanout] starting pid=%d run_id=%s streams=%d timeout_secs=%.1f",
        os.getpid(), run_id, len(stream_configs), timeout_secs,
    )
    return asyncio.run(_run_all(run_id, stream_configs, timeout_secs))


# ---------------------------------------------------------------------------
# Async implementation
# ---------------------------------------------------------------------------


async def _run_all(
    run_id: str,
    stream_configs: list[dict[str, Any]],
    timeout_secs: float,
) -> dict[str, Any]:
    """Launch all streams concurrently and return per-stream results.

    Wraps ``asyncio.gather`` in ``asyncio.wait_for`` so a stalled coroutine
    can never leave this task running indefinitely.  An ``asyncio.Semaphore``
    limits concurrent XADD calls to :data:`_XADD_CONCURRENCY` to prevent
    Redis connection pool exhaustion when hundreds of streams flush simultaneously.

    Args:
        run_id:         Shared run UUID (for log correlation only).
        stream_configs: Per-stream config dicts.
        timeout_secs:   Hard deadline.

    Returns:
        Dict mapping ``stream_id`` → result dict.
    """
    xadd_semaphore = asyncio.Semaphore(_XADD_CONCURRENCY)
    tasks = [
        _ingest_one(cfg, timeout_secs, run_id, xadd_semaphore)
        for cfg in stream_configs
    ]
    hard_timeout = timeout_secs + _WAIT_FOR_GRACE_SECS
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=hard_timeout,
        )
    except asyncio.TimeoutError:
        logger.error(
            "[fanout] hard timeout hit after %.1fs run_id=%s streams=%d — "
            "some done_keys may not have been pushed",
            hard_timeout, run_id, len(stream_configs),
        )
        # Return empty results; individual _ingest_one finally blocks already
        # pushed done_keys for any streams that completed before the timeout.
        return {}

    out: dict[str, Any] = {}
    for cfg, result in zip(stream_configs, results):
        sid = cfg["stream_id"]
        if isinstance(result, Exception):
            logger.warning(
                "[fanout] stream error stream_id=%s run_id=%s: %s",
                sid, run_id, result,
            )
            out[sid] = {"produced": 0, "stop_reason": "error", "ingest_ms": 0}
        else:
            out[sid] = result
    logger.info("[fanout] all streams done run_id=%s", run_id)
    return out


async def _ingest_one(
    cfg: dict[str, Any],
    timeout_secs: float,
    run_id: str,
    xadd_semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    """Run the full-duration rate-limited ingest for one stream.

    Registers with the governance registry on first call, then runs the
    mock LLM loop for up to ``timeout_secs``, flushing token batches to
    Redis Streams.  Stops early on a frontend stable signal.

    Result is pushed to ``cfg["done_key"]`` (RPUSH) on completion so the
    FastAPI dispatcher's BLPOP is satisfied immediately.

    Args:
        cfg:          Per-stream config dict (see :func:`run_fanout_batch`).
        timeout_secs: Hard deadline for this stream.
        run_id:       Shared run UUID (for log correlation).

    Returns:
        Dict with ``produced``, ``stop_reason``, ``ingest_ms``.
    """
    from backend.llm.providers.mock import get_mock_llm  # noqa: PLC0415
    from backend.db.redis.session.perf_stable_signal import (  # noqa: PLC0415
        check_and_consume_perf_stable,
    )
    from backend.graph.governance import register_stream, deregister_stream  # noqa: PLC0415
    from backend.db.redis.router import get_redis_router  # noqa: PLC0415

    stream_id: str = cfg["stream_id"]
    thread_id: str = cfg["thread_id"]
    node_id: str = cfg["node_id"]
    task_id: str = cfg["task_id"]
    pub_task_id: str = cfg["pub_task_id"]
    task_name: str = cfg["task_name"]
    token_per_sec: int = int(cfg["token_per_sec"])
    done_key: str = cfg["done_key"]
    node_name: str = task_name.split(".")[0]

    effective_tps = max(token_per_sec, 1)
    batch_delay = _FLUSH_SIZE / effective_tps

    mock_llm = get_mock_llm(thread_id=thread_id, timeout_secs=timeout_secs, stream_id=stream_id)

    produced = 0
    stop_reason = "timeout"
    ingest_ms = 0
    t_start = time.monotonic()
    pending_batch: list[str] = []
    token_window: deque[str] = deque(maxlen=10)
    t_batch_start = t_start

    logger.info(
        "[fanout_stream] start stream_id=%s run_id=%s timeout_secs=%.1f tps=%d",
        stream_id, run_id, timeout_secs, effective_tps,
    )

    try:
        await register_stream(thread_id, node_id, task_id, stream_id)
    except Exception:  # noqa: BLE001
        logger.warning("[fanout_stream] register_stream failed stream_id=%s", stream_id)

    try:
        async for chunk in mock_llm._astream([]):
            if time.monotonic() - t_start >= timeout_secs:
                break
            token: str = chunk.message.content
            if token:
                pending_batch.append(token)
                token_window.append(token.strip())
                produced += 1
            if len(pending_batch) >= _FLUSH_SIZE:
                await _flush_batch(
                    thread_id, stream_id, pub_task_id, task_name, node_name,
                    len(pending_batch), list(token_window),
                    xadd_semaphore=xadd_semaphore,
                )
                if produced == len(pending_batch):  # first flush
                    logger.debug(
                        "[fanout_stream] first_flush produced=%d elapsed=%.3fs stream_id=%s",
                        produced, time.monotonic() - t_start, stream_id,
                    )
                pending_batch = []
                if await check_and_consume_perf_stable(stream_id, thread_id):
                    stop_reason = "stable"
                    break
                batch_elapsed = time.monotonic() - t_batch_start
                sleep_time = batch_delay - batch_elapsed
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                t_batch_start = time.monotonic()

        if pending_batch:
            await _flush_batch(
                thread_id, stream_id, pub_task_id, task_name, node_name,
                len(pending_batch), list(token_window),
                xadd_semaphore=xadd_semaphore,
            )

        if stop_reason == "timeout":
            if await check_and_consume_perf_stable(stream_id, thread_id):
                stop_reason = "stable"

    finally:
        ingest_ms = int((time.monotonic() - t_start) * 1000)
        try:
            await deregister_stream(thread_id, node_id, task_id, stream_id)
        except Exception:  # noqa: BLE001
            logger.warning("[fanout_stream] deregister_stream failed stream_id=%s", stream_id)

        result_json = json.dumps({
            "produced": produced,
            "stop_reason": stop_reason,
            "ingest_ms": ingest_ms,
        })
        try:
            router = get_redis_router()
            # Route done_key by stream_id — consistent with coordinator BLPOP
            # which also routes by stream_id, and deterministic from stream_id alone.
            client = router.get_client_for_stream(stream_id)
            await client.rpush(done_key, result_json)
            await client.expire(done_key, _DONE_KEY_TTL_SECS)
        except Exception:  # noqa: BLE001
            logger.exception(
                "[fanout_stream] failed to push done_key stream_id=%s", stream_id
            )

    logger.info(
        "[fanout_stream] done produced=%d stop_reason=%s ingest_ms=%d stream_id=%s run_id=%s",
        produced, stop_reason, ingest_ms, stream_id, run_id,
    )
    if produced == 0:
        logger.warning(
            "[fanout_stream] ZERO TOKENS produced — check Centrifugo delivery for this thread. "
            "stream_id=%s thread_id=%s run_id=%s ingest_ms=%d",
            stream_id, thread_id, run_id, ingest_ms,
        )
    return {"produced": produced, "stop_reason": stop_reason, "ingest_ms": ingest_ms}


async def _flush_batch(
    thread_id: str,
    stream_id: str,
    pub_task_id: str,
    task_name: str,
    node_name: str,
    count: int,
    recent_tokens: list[str],
    *,
    xadd_semaphore: asyncio.Semaphore,
) -> None:
    """XADD one ``token_batch`` publication to ``fin:llm:tokens``.

    Args:
        thread_id:      LangGraph thread UUID.
        stream_id:      Per-stream UUID (for log correlation).
        pub_task_id:  Task row UUID embedded in the event.
        task_name:       Full task key string.
        node_name:      Agent node name prefix.
        count:          Number of tokens in this batch.
        recent_tokens:  Rolling window of last 10 token strings.
        xadd_semaphore: Shared semaphore limiting concurrent XADD calls.
    """
    event: dict[str, Any] = {
        "event": "token_batch",
        "task_id": pub_task_id,
        "node_name": node_name,
        "task_name": task_name,
        "count": count,
        "recent_tokens": recent_tokens,
    }
    payload_value = json.dumps({"channel": f"thread:{thread_id}", "data": event})
    try:
        async with xadd_semaphore:
            await xadd_sharded(
                thread_id,
                STREAM_TOKEN,
                {"method": "publish", "payload": payload_value},
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[fanout_stream] xadd failed count=%d stream_id=%s: %s",
            count, stream_id, exc,
        )


__all__ = ["run_fanout_batch"]
