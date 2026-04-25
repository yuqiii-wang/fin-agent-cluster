"""Split ingest + adaptive reader — concurrent Phase-2 perf-test pipeline.

Architecture
------------
Phase 1 — first-phase ingest (:func:`run_ingest_first_half`)
    Clears the stream and bulk-writes 95 % of ``total_tokens`` via an async
    Redis pipeline.  Does **not** append the end-of-stream sentinel —
    that is deferred to Phase 2.  Emits ``perf_ingest_progress`` SSE events
    approximately every second.

Phase 2 — concurrent ingest + read (same Celery worker / event loop)
    Two coroutines are launched via ``asyncio.gather`` so that write and read
    for the same streaming ID happen in the same worker:

    * :func:`run_ingest_second_half` — bulk-writes the remaining 5 % of
      tokens and finally appends the sentinel, updating the shared
      :class:`_ConcurrentProgress` object with a rolling ingest TPS figure.

    * :func:`dynamic_reader_gen` — async generator consumed by
      ``stream_perf_text_task``.  Reads with an adaptive batch size:

      - Initial window (first 3 s): batch_size = 1 (one token at a time).
      - After first window: base batch_size = 3, then every 3 s:

        * If ingest is active → scale batch_size so
          ``digest_tps ≈ 1.5 × ingest_tps`` (drain faster than write).
        * If ingest finished → gradually reduce toward 3.
        * Stream backlog < ``_NEAR_EMPTY_THRESHOLD`` → clamp to 1.
        * Stream exhausted + ingest done → exit.

      Emits ``perf_concurrent_status`` via Redis Streams every 3 s so the
      frontend can display live batch_size, digest TPS, ingest TPS and backlog.

The dedicated :mod:`~backend.graph.agents.perf_test.celery_ingest` package
exists for deployments that want to offload bulk writes to a separate worker
process — it is not used in the default in-process path.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from collections.abc import AsyncGenerator

from backend.db.redis.streams.publisher import stream_token
from backend.db.redis.router import get_redis_router
from backend.sse_notifications.perf_test.notifications import (
    emit_perf_ingest_progress,
)
from backend.graph.agents.perf_test.celery_ingest.config import (
    PERF_INGEST_BATCH_SIZE,
    PERF_INGEST_SENTINEL_FIELD,
    PERF_INGEST_SENTINEL_VALUE,
    PERF_INGEST_STREAM_MAXLEN,
    PERF_INGEST_STREAM_PREFIX,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Adaptive reader constants
# ---------------------------------------------------------------------------

#: Initial read batch size — one token at a time (first measurement window).
_READER_INITIAL_BATCH: int = 1
#: Batch size when entering the adaptive window phase (post warmup).
_READER_BASE_BATCH: int = 3
#: Target digest/ingest TPS ratio — reader aims to drain 1.5× faster than write.
_TARGET_DIGEST_RATIO: float = 1.5
#: Duration of each adaptive evaluation window in seconds.
_WINDOW_SECS: float = 1.0
#: Stream backlog below which batch is clamped to 1 (stream nearly empty).
_NEAR_EMPTY_THRESHOLD: int = 50
#: Hard upper bound on batch size — aggressive but bounded drain cap.
_MAX_BATCH_SIZE: int = 1_000
#: When stream backlog >= this, the full _MAX_BATCH_SIZE is permitted.
_LARGE_QUEUE_THRESHOLD: int = 1_000
#: Maximum milliseconds to block on XREAD when stream is caught up to ingest.
_XREAD_BLOCK_MS: int = 1_000


# ---------------------------------------------------------------------------
# Shared mutable state (concurrent ingest ↔ reader, same event loop)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _ConcurrentProgress:
    """Mutable shared state updated by :func:`run_ingest_second_half` and read
    by :func:`dynamic_reader_gen`.

    Both coroutines run in the same asyncio event loop so no locking is needed.

    Attributes:
        ingest_tps:   Rolling tokens/second for the ongoing second-half ingest.
        ingest_done:  True once the second-half ingest (including sentinel) is complete.
        produced:     Total tokens produced so far (both halves combined).
        stable:       Set to True by :func:`signal_stable_ingest` when the frontend
                      signals that TPS has stabilised and the stream should conclude
                      cleanly with ``perf_test_complete`` instead of a timeout.
    """

    ingest_tps: float = 0.0
    ingest_done: bool = False
    produced: int = 0
    stable: bool = False


# ---------------------------------------------------------------------------
# In-process stable-signal registry (FastAPI event loop only)
# ---------------------------------------------------------------------------

# Maps thread_id → active _ConcurrentProgress for ongoing concurrency sessions.
# Populated by node.py before asyncio.gather; cleared when the gather returns.
_active_ingest: dict[str, _ConcurrentProgress] = {}


def register_concurrency_ingest(thread_id: str, progress: _ConcurrentProgress) -> None:
    """Register an active concurrency ingest so the stable-signal endpoint can reach it.

    Args:
        thread_id: LangGraph thread UUID.
        progress:  Shared progress object for this session.
    """
    _active_ingest[thread_id] = progress


def unregister_concurrency_ingest(thread_id: str) -> None:
    """Remove the active ingest entry once the concurrency gather completes.

    Args:
        thread_id: LangGraph thread UUID.
    """
    _active_ingest.pop(thread_id, None)


def signal_stable_ingest(thread_id: str) -> bool:
    """Signal that the frontend has detected stable TPS for this concurrency session.

    Sets :attr:`_ConcurrentProgress.stable` to True so that
    :func:`run_rate_limited_ingest` exits its loop at the next batch boundary,
    appends the sentinel, and returns ``(produced, "stable")`` instead of
    ``(produced, "timeout")``.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        True if the session was found and signalled; False if not found
        (e.g. the timeout already fired and the gather has returned).
    """
    progress = _active_ingest.get(thread_id)
    if progress is None:
        return False
    progress.stable = True
    return True


# ---------------------------------------------------------------------------
# Phase 1: first-half ingest
# ---------------------------------------------------------------------------


async def run_ingest_first_half(
    thread_id: str,
    total_tokens: int,
    timeout_secs: float,
) -> tuple[int, str]:
    """Bulk-write 95 % of tokens to ``fin:perf:{thread_id}`` via async pipeline.

    Clears any leftover stream before writing.  Does **not** append the
    sentinel — that is deferred to :func:`run_ingest_second_half` so the
    reader only terminates after all tokens are written.

    Emits ``perf_ingest_progress`` SSE events approximately every second.

    Args:
        thread_id:    LangGraph thread UUID.
        total_tokens: Total token budget for the full test run.
        timeout_secs: Hard deadline measured from the start of the node.

    Returns:
        Tuple ``(produced, stop_reason)`` where *stop_reason* is
        ``"half_done"`` (normal — 95 % threshold reached) or ``"timeout"``
        (deadline fired before threshold was written).
    """
    threshold = int(total_tokens * 0.95)
    client = get_redis_router().get_client_for_thread(thread_id)
    stream = f"{PERF_INGEST_STREAM_PREFIX}:{thread_id}"
    await client.delete(stream)

    produced = 0
    t_start = time.monotonic()
    stop_reason = "half_done"
    t_last_progress = t_start

    logger.info(
        "[run_ingest_first_half] starting threshold=%d total=%d timeout=%.1fs thread_id=%s",
        threshold, total_tokens, timeout_secs, thread_id,
    )

    while produced < threshold:
        elapsed = time.monotonic() - t_start
        if elapsed > timeout_secs:
            stop_reason = "timeout"
            logger.warning(
                "[run_ingest_first_half] timeout produced=%d/%d thread_id=%s",
                produced, threshold, thread_id,
            )
            break

        batch = min(PERF_INGEST_BATCH_SIZE, threshold - produced)
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

        now = time.monotonic()
        if now - t_last_progress >= 1.0:
            t_last_progress = now
            ingest_elapsed = now - t_start
            await emit_perf_ingest_progress(
                thread_id,
                produced=produced,
                total_tokens=total_tokens,
                elapsed_ms=int(ingest_elapsed * 1000),
                ingest_tps=produced / max(ingest_elapsed, 0.001),
                status="running",
            )

        await asyncio.sleep(0)

    elapsed = time.monotonic() - t_start
    await emit_perf_ingest_progress(
        thread_id,
        produced=produced,
        total_tokens=total_tokens,
        elapsed_ms=int(elapsed * 1000),
        ingest_tps=produced / max(elapsed, 0.001),
        status=stop_reason,
    )
    logger.info(
        "[run_ingest_first_half] done produced=%d stop_reason=%s elapsed=%.2fs thread_id=%s",
        produced, stop_reason, elapsed, thread_id,
    )
    return produced, stop_reason


# ---------------------------------------------------------------------------
# Phase 2a: second-half ingest (concurrent with dynamic reader)
# ---------------------------------------------------------------------------


async def run_ingest_second_half(
    thread_id: str,
    first_half_produced: int,
    total_tokens: int,
    timeout_secs: float,
    t_global_start: float,
    progress: _ConcurrentProgress,
) -> tuple[int, str]:
    """Bulk-write the remaining 5 % of tokens then append the end-of-stream sentinel.

    Runs concurrently with :func:`dynamic_reader_gen` via ``asyncio.gather``
    in the same Celery worker event loop.  Updates *progress* each batch so
    the reader can adjust its batch size in real time.

    Emits ``perf_ingest_progress`` SSE events approximately every second.

    Args:
        thread_id:           LangGraph thread UUID.
        first_half_produced: Tokens already written during Phase 1.
        total_tokens:        Full token budget.
        timeout_secs:        Hard deadline measured from ``t_global_start``.
        t_global_start:      ``time.monotonic()`` captured at node entry.
        progress:            Shared mutable state updated in place.

    Returns:
        Tuple ``(additional_produced, stop_reason)`` for the second half only,
        where *stop_reason* is ``"completed"`` or ``"timeout"``.
    """
    client = get_redis_router().get_client_for_thread(thread_id)
    stream = f"{PERF_INGEST_STREAM_PREFIX}:{thread_id}"

    produced = first_half_produced
    stop_reason = "completed"
    t_window_start = time.monotonic()
    window_start_count = first_half_produced
    t_last_progress = time.monotonic()
    t_phase_start = time.monotonic()

    logger.info(
        "[run_ingest_second_half] starting from=%d to=%d thread_id=%s",
        first_half_produced, total_tokens, thread_id,
    )

    while produced < total_tokens:
        if time.monotonic() - t_global_start > timeout_secs:
            stop_reason = "timeout"
            logger.warning(
                "[run_ingest_second_half] timeout produced=%d/%d thread_id=%s",
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
        progress.produced = produced

        # Update rolling 1-second ingest TPS for the adaptive reader.
        now = time.monotonic()
        window_elapsed = now - t_window_start
        if window_elapsed >= 1.0:
            progress.ingest_tps = (produced - window_start_count) / window_elapsed
            t_window_start = now
            window_start_count = produced

        # Emit progress event ~every second.
        if now - t_last_progress >= 1.0:
            t_last_progress = now
            total_elapsed = now - t_global_start
            await emit_perf_ingest_progress(
                thread_id,
                produced=produced,
                total_tokens=total_tokens,
                elapsed_ms=int(total_elapsed * 1000),
                ingest_tps=progress.ingest_tps,
                status="running",
            )

        await asyncio.sleep(0)

    # Append sentinel so the reader knows ingest is finished.
    await client.xadd(stream, {PERF_INGEST_SENTINEL_FIELD: PERF_INGEST_SENTINEL_VALUE})
    progress.ingest_done = True
    progress.ingest_tps = 0.0

    additional = produced - first_half_produced
    phase_elapsed = time.monotonic() - t_phase_start
    total_elapsed = time.monotonic() - t_global_start
    await emit_perf_ingest_progress(
        thread_id,
        produced=produced,
        total_tokens=total_tokens,
        elapsed_ms=int(total_elapsed * 1000),
        ingest_tps=additional / max(phase_elapsed, 0.001),
        status=stop_reason,
    )
    logger.info(
        "[run_ingest_second_half] done additional=%d stop_reason=%s thread_id=%s",
        additional, stop_reason, thread_id,
    )
    return additional, stop_reason


# ---------------------------------------------------------------------------
# Phase 2b: dynamic adaptive reader (concurrent with second-half ingest)
# ---------------------------------------------------------------------------


async def dynamic_reader_gen(
    thread_id: str,
    progress: _ConcurrentProgress,
) -> AsyncGenerator[str, None]:
    """Yield tokens from ``fin:perf:{thread_id}`` with adaptive batch sizing.

    Batch size control (evaluated every :data:`_WINDOW_SECS` seconds):

    * **Warmup window** (first 3 s): ``batch_size = 1`` — reads one token at a
      time to establish baseline measurements.
    * **Adaptive windows**: base ``batch_size = 3``; scaled every 3 s:

      - Ingest active → ``batch_size`` adjusted so
        ``digest_tps ≈ _TARGET_DIGEST_RATIO × ingest_tps`` (drain 1.5× faster).
      - Ingest done → reduce toward 3 (``max(3, size − size // 5)``).
      - Stream backlog < ``_NEAR_EMPTY_THRESHOLD`` → clamp to 1.
      - Stream exhausted + ingest done → exit generator.

    Uses blocking XREAD (:data:`_XREAD_BLOCK_MS` ms) so the event loop is
    yielded while waiting for new tokens rather than spinning.

    Emits ``perf_concurrent_status`` via Redis Streams every window so the
    frontend receives live batch_size, digest/ingest TPS, and stream backlog.

    Args:
        thread_id: LangGraph thread UUID.
        progress:  Shared state updated by the concurrent ingest coroutine.

    Yields:
        Token strings from the perf stream until the sentinel is reached.
    """
    client = get_redis_router().get_client_for_thread(thread_id)
    stream = f"{PERF_INGEST_STREAM_PREFIX}:{thread_id}"
    last_id = "0-0"

    batch_size = _READER_INITIAL_BATCH
    window_start = time.monotonic()
    window_published = 0
    first_window = True

    logger.info("[dynamic_reader_gen] starting thread_id=%s", thread_id)

    # Emit an initial status immediately so the UI shows batch_size=1 even for
    # very fast throughput-mode Phase-2 runs that complete in < _WINDOW_SECS.
    # Uses stream_token (Redis Streams) for the same low-latency path as
    # perf_token_batch, avoiding the lifecycle channel roundtrip.
    await stream_token(
        thread_id,
        {
            "event": "perf_concurrent_status",
            "batch_size": batch_size,
            "digest_tps": 0.0,
            "ingest_tps": round(progress.ingest_tps, 1),
            "stream_len": 0,
        },
    )

    while True:
        now = time.monotonic()
        elapsed_window = now - window_start

        # ── Current stream backlog (single XLEN per loop iteration) ─────────
        stream_len = await client.xlen(stream)

        # ── Adaptive batch-size evaluation every _WINDOW_SECS seconds ──────
        if elapsed_window >= _WINDOW_SECS:
            digest_tps = window_published / max(elapsed_window, 0.001)
            ingest_tps = progress.ingest_tps

            if first_window:
                # End of warmup: if a large backlog has accumulated already,
                # jump straight to max batch so we don't crawl at 3 for another
                # full window while thousands of tokens sit in the stream.
                if stream_len >= _LARGE_QUEUE_THRESHOLD:
                    batch_size = _MAX_BATCH_SIZE
                else:
                    batch_size = _READER_BASE_BATCH
                first_window = False
            elif ingest_tps > 0:
                # Scale to target digest_tps ≈ 1.5 × ingest_tps.
                target_tps = _TARGET_DIGEST_RATIO * ingest_tps
                if digest_tps > 0:
                    ratio = target_tps / digest_tps
                    batch_size = max(
                        _READER_BASE_BATCH,
                        min(_MAX_BATCH_SIZE, round(batch_size * ratio)),
                    )
                else:
                    batch_size = _READER_BASE_BATCH
            elif not progress.ingest_done:
                # Ingest transiently at 0 TPS but not yet finished; hold base.
                batch_size = _READER_BASE_BATCH
            else:
                # Ingest finished: if the backlog is still large, drain at max
                # speed; otherwise gradually reduce toward 3.
                if stream_len >= _LARGE_QUEUE_THRESHOLD:
                    batch_size = _MAX_BATCH_SIZE
                else:
                    batch_size = max(_READER_BASE_BATCH, batch_size - max(1, batch_size // 5))

            # Over-read guard: when the queue is below _LARGE_QUEUE_THRESHOLD
            # and the computed batch exceeds what is actually in the stream,
            # clamp to stream_len (read everything that is there) rather than
            # snapping to an arbitrary small constant.  The near-empty clamp
            # below still reduces effective_batch to 1 when stream_len < 50.
            if stream_len < _LARGE_QUEUE_THRESHOLD and batch_size > stream_len:
                batch_size = max(_READER_BASE_BATCH, stream_len)

            # Stop auditing once ingest has reached 100% — no more concurrent
            # status events are meaningful after the write side is finished.
            # Uses stream_token (Redis Streams) for sub-millisecond delivery
            # via the same path as perf_token_batch events.
            if not progress.ingest_done:
                await stream_token(
                    thread_id,
                    {
                        "event": "perf_concurrent_status",
                        "batch_size": batch_size,
                        "digest_tps": round(digest_tps, 1),
                        "ingest_tps": round(ingest_tps, 1),
                        "stream_len": stream_len,
                    },
                )
            logger.debug(
                "[dynamic_reader_gen] window batch_size=%d digest_tps=%.1f "
                "ingest_tps=%.1f stream_len=%d thread_id=%s",
                batch_size, digest_tps, ingest_tps, stream_len, thread_id,
            )
            window_start = now
            window_published = 0

        # ── Near-empty clamp (applied per-loop, after the audit window) ────
        effective_batch = 1 if stream_len < _NEAR_EMPTY_THRESHOLD else batch_size

        # Blocking XREAD yields the event loop while waiting for new tokens.
        results = await client.xread(
            streams={stream: last_id},
            count=max(1, effective_batch),
            block=_XREAD_BLOCK_MS,
        )

        if not results:
            # Timed out waiting — check if ingest is finished.
            if progress.ingest_done:
                break
            continue

        _, messages = results[0]
        for msg_id, fields in messages:
            last_id = msg_id
            if fields.get(PERF_INGEST_SENTINEL_FIELD) == PERF_INGEST_SENTINEL_VALUE:
                logger.info(
                    "[dynamic_reader_gen] sentinel reached thread_id=%s",
                    thread_id,
                )
                return
            token = fields.get("t", "")
            if token:
                yield token
                window_published += 1

        await asyncio.sleep(0)

    logger.info("[dynamic_reader_gen] stream exhausted thread_id=%s", thread_id)


# ---------------------------------------------------------------------------
# Concurrency mode: rate-limited ingest (no Phase 1 pre-load)
# ---------------------------------------------------------------------------


async def run_rate_limited_ingest(
    thread_id: str,
    token_per_sec: int,
    timeout_secs: float,
    t_global_start: float,
    progress: _ConcurrentProgress,
) -> tuple[int, str]:
    """Write tokens at a fixed rate for *timeout_secs*, then append the sentinel.

    Used in concurrency test mode: no Phase-1 pre-ingest is performed; tokens
    are written at a steady ``token_per_sec`` rate and simultaneously consumed
    by :func:`dynamic_reader_gen` via ``asyncio.gather``.

    Batch sizing: writes ``batch_size = max(1, min(PERF_INGEST_BATCH_SIZE,
    token_per_sec // 10))`` tokens per write, sleeping for the remaining time
    in each 100 ms window to achieve the target rate without busy-waiting.

    Emits ``perf_ingest_progress`` SSE events approximately every second.

    Args:
        thread_id:       LangGraph thread UUID.
        token_per_sec:   Target ingest rate in tokens per second.
        timeout_secs:    Duration to ingest for (measured from *t_global_start*).
        t_global_start:  ``time.monotonic()`` captured at node entry.
        progress:        Shared mutable state updated in place.

    Returns:
        Tuple ``(produced, "timeout")`` — concurrency mode always ends at timeout.
    """
    client = get_redis_router().get_client_for_thread(thread_id)
    stream = f"{PERF_INGEST_STREAM_PREFIX}:{thread_id}"
    await client.delete(stream)

    # Batch sizing: ~10 writes per second so Redis round-trip overhead is
    # amortised while the event loop is yielded frequently.
    batch_size = max(1, min(PERF_INGEST_BATCH_SIZE, max(1, token_per_sec) // 10))
    delay = batch_size / max(token_per_sec, 1)  # target seconds between writes

    produced = 0
    t_phase_start = time.monotonic()
    t_last_progress = t_phase_start

    logger.info(
        "[run_rate_limited_ingest] starting token_per_sec=%d batch_size=%d "
        "delay=%.3fs timeout=%.1fs thread_id=%s",
        token_per_sec, batch_size, delay, timeout_secs, thread_id,
    )

    stop_reason = "timeout"
    while time.monotonic() - t_global_start < timeout_secs:
        t_batch = time.monotonic()

        async with client.pipeline(transaction=False) as pipe:
            for i in range(batch_size):
                seq = produced + i + 1
                pipe.xadd(
                    stream,
                    {"t": f"mock_msg_{thread_id}_{seq}"},
                    maxlen=PERF_INGEST_STREAM_MAXLEN,
                    approximate=True,
                )
            await pipe.execute()

        produced += batch_size
        progress.produced = produced
        progress.ingest_tps = float(token_per_sec)

        # Rate-limit: sleep for the remaining portion of the batch window.
        batch_elapsed = time.monotonic() - t_batch
        sleep_secs = max(0.0, delay - batch_elapsed)
        if sleep_secs > 0:
            await asyncio.sleep(sleep_secs)
        else:
            await asyncio.sleep(0)  # always yield the event loop

        # Check stable signal from frontend — exit early with "stable" reason.
        if progress.stable:
            stop_reason = "stable"
            break

        # Emit progress event approximately every second.
        now = time.monotonic()
        if now - t_last_progress >= 1.0:
            t_last_progress = now
            phase_elapsed = now - t_phase_start
            await emit_perf_ingest_progress(
                thread_id,
                produced=produced,
                total_tokens=0,  # 0 signals "no fixed total" to the frontend
                elapsed_ms=int(phase_elapsed * 1000),
                ingest_tps=produced / max(phase_elapsed, 0.001),
                status="running",
            )

    # Append sentinel so dynamic_reader_gen knows ingest is complete.
    await client.xadd(stream, {PERF_INGEST_SENTINEL_FIELD: PERF_INGEST_SENTINEL_VALUE})
    progress.ingest_done = True
    progress.ingest_tps = 0.0

    phase_elapsed = time.monotonic() - t_phase_start
    final_status = "completed" if stop_reason == "stable" else "timeout"
    await emit_perf_ingest_progress(
        thread_id,
        produced=produced,
        total_tokens=0,
        elapsed_ms=int(phase_elapsed * 1000),
        ingest_tps=produced / max(phase_elapsed, 0.001),
        status=final_status,
    )
    logger.info(
        "[run_rate_limited_ingest] done produced=%d elapsed=%.2fs stop_reason=%s thread_id=%s",
        produced, phase_elapsed, stop_reason, thread_id,
    )
    return produced, stop_reason


__all__ = [
    "_ConcurrentProgress",
    "run_ingest_first_half",
    "run_ingest_second_half",
    "run_rate_limited_ingest",
    "dynamic_reader_gen",
    "register_concurrency_ingest",
    "unregister_concurrency_ingest",
    "signal_stable_ingest",
]

