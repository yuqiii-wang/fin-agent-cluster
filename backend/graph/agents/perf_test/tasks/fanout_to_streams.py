"""run_ingest / perf_stream_reader_gen — bulk token production via async pipeline.

:func:`run_ingest` writes all mock tokens to ``fin:perf:{thread_id}`` using
an asyncio Redis pipeline (batch XADD, no per-token round-trips) directly in
the FastAPI event loop — no external Celery workers needed.  A cooperative
``await asyncio.sleep(0)`` between batches yields the event loop so SSE and
other coroutines remain responsive.

:func:`perf_stream_reader_gen` reads back from the same stream for the pub
phase.  Because ingest completes fully before the pub task starts, every read
is a non-blocking XREAD against a fully populated stream.

The dedicated :mod:`~backend.graph.agents.perf_test.celery_ingest` package
exists for deployments that want to offload bulk writes to a separate worker
process — it is not used in the default in-process path.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator

import redis.asyncio as aioredis

from backend.config import get_settings
from backend.db.redis.publisher import stream_token
from backend.graph.agents.perf_test.celery_ingest.config import (
    PERF_INGEST_BATCH_SIZE,
    PERF_INGEST_SENTINEL_FIELD,
    PERF_INGEST_SENTINEL_VALUE,
    PERF_INGEST_STREAM_MAXLEN,
    PERF_INGEST_STREAM_PREFIX,
    PERF_PUB_READ_BATCH_SIZE,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared async Redis client
# ---------------------------------------------------------------------------

_client: aioredis.Redis | None = None
_client_loop_id: int | None = None


async def _get_client() -> aioredis.Redis:
    """Return (or lazily create) the shared async Redis client.

    Recreated when the running event loop changes to avoid stale connection
    pools.

    Returns:
        A ``redis.asyncio.Redis`` instance.
    """
    global _client, _client_loop_id
    current_id = id(asyncio.get_running_loop())
    if _client is not None and _client_loop_id != current_id:
        try:
            await _client.aclose()
        except Exception:  # noqa: BLE001
            pass
        _client = None
        _client_loop_id = None
    if _client is None:
        settings = get_settings()
        _client = aioredis.from_url(
            settings.DATABASE_REDIS_URL,
            decode_responses=True,
        )
        _client_loop_id = current_id
    return _client


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_ingest(
    thread_id: str,
    total_tokens: int,
    timeout_secs: float,
) -> tuple[int, str]:
    """Bulk-write mock tokens to ``fin:perf:{thread_id}`` via async pipeline.

    Writes tokens in batches of :data:`~celery_ingest.config.PERF_INGEST_BATCH_SIZE`
    using a Redis pipeline (one round-trip per batch, not per token).
    Between batches the event loop is yielded via ``await asyncio.sleep(0)``
    so SSE and other coroutines remain responsive.  When done (or on timeout)
    a sentinel entry is appended so :func:`perf_stream_reader_gen` knows to stop.

    Args:
        thread_id:    LangGraph thread UUID.
        total_tokens: Target number of tokens to produce.
        timeout_secs: Hard deadline; if elapsed the sentinel is still written
                      so the pub reader terminates cleanly.

    Returns:
        Tuple ``(produced, stop_reason)`` where *stop_reason* is
        ``"completed"`` (full budget written) or ``"timeout"`` (deadline
        fired before all tokens were written).
    """
    client = await _get_client()
    stream = f"{PERF_INGEST_STREAM_PREFIX}:{thread_id}"
    # Clean any leftover stream from a previous run.
    await client.delete(stream)

    produced = 0
    t_start = time.monotonic()
    stop_reason = "completed"
    t_last_progress = t_start  # last time a progress event was emitted

    logger.info(
        "[run_ingest] starting total_tokens=%d timeout_secs=%.1f thread_id=%s",
        total_tokens, timeout_secs, thread_id,
    )

    while produced < total_tokens:
        elapsed = time.monotonic() - t_start
        if elapsed > timeout_secs:
            stop_reason = "timeout"
            logger.warning(
                "[run_ingest] timeout produced=%d/%d thread_id=%s",
                produced, total_tokens, thread_id,
            )
            break

        batch = min(PERF_INGEST_BATCH_SIZE, total_tokens - produced)
        async with client.pipeline(transaction=False) as pipe:
            for i in range(batch):
                seq = produced + i + 1
                pipe.xadd(
                    stream,
                    {"t": f"mock_msg_{thread_id}_{seq}"},
                    maxlen=PERF_INGEST_STREAM_MAXLEN,
                    approximate=True,
                )
            await pipe.execute()

        produced += batch
        logger.debug(
            "[run_ingest] batch done produced=%d/%d thread_id=%s",
            produced, total_tokens, thread_id,
        )

        # Emit progress event approximately every second.
        now = time.monotonic()
        if now - t_last_progress >= 1.0:
            t_last_progress = now
            ingest_elapsed = now - t_start
            await stream_token(
                thread_id,
                {
                    "event": "perf_ingest_progress",
                    "produced": produced,
                    "total_tokens": total_tokens,
                    "elapsed_ms": int(ingest_elapsed * 1000),
                    "ingest_tps": round(produced / max(ingest_elapsed, 0.001)),
                    "status": "running",
                },
            )

        # Yield the event loop between batches so other coroutines can run.
        await asyncio.sleep(0)

    # Append sentinel so perf_stream_reader_gen terminates cleanly.
    await client.xadd(stream, {PERF_INGEST_SENTINEL_FIELD: PERF_INGEST_SENTINEL_VALUE})

    elapsed = time.monotonic() - t_start
    # Emit final progress event so the UI reflects the definitive produced count.
    await stream_token(
        thread_id,
        {
            "event": "perf_ingest_progress",
            "produced": produced,
            "total_tokens": total_tokens,
            "elapsed_ms": int(elapsed * 1000),
            "ingest_tps": round(produced / max(elapsed, 0.001)),
            "status": stop_reason,
        },
    )
    logger.info(
        "[run_ingest] done produced=%d stop_reason=%s elapsed=%.2fs thread_id=%s",
        produced, stop_reason, elapsed, thread_id,
    )
    return produced, stop_reason


async def perf_stream_reader_gen(thread_id: str) -> AsyncGenerator[str, None]:
    """Yield tokens from ``fin:perf:{thread_id}`` until the sentinel is reached.

    Designed for the pub task: after :func:`run_ingest` completes all tokens
    are already written so every XREAD is a non-blocking fetch against a fully
    populated stream.  Terminates when it encounters the end-of-stream sentinel
    entry written by :func:`run_ingest`.

    Args:
        thread_id: LangGraph thread UUID.

    Yields:
        Token strings written during the ingest phase.
    """
    client = await _get_client()
    stream = f"{PERF_INGEST_STREAM_PREFIX}:{thread_id}"
    last_id = "0-0"

    while True:
        results = await client.xread(
            streams={stream: last_id},
            count=PERF_PUB_READ_BATCH_SIZE,
        )
        if not results:
            break
        _, messages = results[0]
        for msg_id, fields in messages:
            last_id = msg_id
            if fields.get(PERF_INGEST_SENTINEL_FIELD) == PERF_INGEST_SENTINEL_VALUE:
                return  # sentinel reached: stop reading
            token = fields.get("t", "")
            if token:
                yield token
        # Yield the event loop between batches.
        await asyncio.sleep(0)


__all__ = ["run_ingest", "perf_stream_reader_gen"]

