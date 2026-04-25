"""SSE event generator — dual-channel fan-in for a single streaming session.

Extracts the full generator logic from ``backend.api.stream`` so the FastAPI
router stays thin (route handlers only).

Architecture
------------
Each SSE session opens **two** Redis channels concurrently:

* ``tokens:<thread_id>`` via Redis Streams (XREAD BLOCK) — high-throughput LLM tokens.
* ``lifecycle:<thread_id>`` via Redis Pub/Sub — task lifecycle events
  (started, completed, failed, cancelled, done, query_received, …).

Both channels are pumped into a single ``asyncio.Queue[str]`` by two
background tasks (``_pump_lifecycle``, ``_pump_tokens``) so the main loop
uses a single ``await merged.get()`` without any ``select``-style juggling.

Session phases
--------------
1. **Replay** — existing DB state is re-emitted so late-connecting clients
   reconstruct the current task list immediately.
2. **Early-exit** — if the query is already terminal, emit ``done`` and close.
3. **Orphan check** — if no asyncio task is active, mark failed/cancelled
   and emit ``done``.
4. **Fan-in loop** — receive events from both channels, filter tokens via the
   watch registry, ACK lifecycle events, handle perf drain, and close on ``done``.

Public API
----------
:func:`build_sse_generator`  — returns an async generator for EventSourceResponse.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator

from fastapi import Request

from backend.api.registry import is_task_active_any_instance
from backend.db.redis.lifecycle.subscriber import read_lifecycle
from backend.db.redis.streams.publisher import (
    ack_pending_notify,
    clear_pending_notify,
    drain_pending_notify,
)
from backend.db.redis.streams.subscriber import read_stream
from backend.sse_notifications.agent_tasks.ack import ack_task_step, increment_task_step_retry
from backend.streaming.lifecycle import (
    LIFECYCLE_EVENTS,
    get_watched_task,
    handle_orphaned_query,
    register_watch,
    replay_existing,
    unregister_watch,
)

logger = logging.getLogger(__name__)

# Maximum events drained per batch iteration so the uvicorn accept loop can
# handle new HTTP connections during high-throughput perf-test delivery.
_MAX_BATCH: int = 50

# Seconds to wait before emitting a keepalive ping and running the drain cycle.
_PING_INTERVAL: float = 25.0

# Seconds to wait for in-flight XREAD responses during the perf pre/post drain.
_PERF_DRAIN_WINDOW: float = 0.1  # 100 ms


async def build_sse_generator(
    thread_id: str,
    request: Request,
) -> AsyncGenerator[dict, None]:
    """Async generator that produces SSE frames for *thread_id*.

    Designed to be passed directly to ``EventSourceResponse``::

        return EventSourceResponse(build_sse_generator(thread_id, request))

    The generator manages channel subscriptions, watch registration, lifecycle
    ACKs, and clean-up on disconnect or ``done``.

    Args:
        thread_id: LangGraph thread UUID from the URL path.
        request:   FastAPI ``Request`` object for disconnect detection.

    Yields:
        ``{"event": str, "data": str}`` dicts consumed by EventSourceResponse.
    """
    logger.debug("[generator] client_connected thread_id=%s", thread_id)
    yield {"event": "connected", "data": json.dumps({"thread_id": thread_id})}

    # ── Phase 1: Replay ────────────────────────────────────────────────────
    replay_events, query_status = await replay_existing(thread_id)
    replayed_task_ids: set[int] = set()

    for evt in replay_events:
        if await request.is_disconnected():
            logger.debug("[generator] disconnected during replay thread_id=%s", thread_id)
            return
        yield evt
        await _register_started_watch(evt, thread_id, replayed_task_ids, "replay")

    # ── Phase 2: Early-exit for terminal queries ───────────────────────────
    if query_status in ("completed", "failed", "cancelled"):
        yield {"event": "done", "data": json.dumps({"event": "done", "status": query_status})}
        return

    # ── Phase 3: Orphan detection ──────────────────────────────────────────
    # Skip for 'received' — query awaits client ACK, live loop handles retries.
    if query_status != "received" and not await is_task_active_any_instance(thread_id):
        final_status = await handle_orphaned_query(thread_id)
        yield {"event": "done", "data": json.dumps({"event": "done", "status": final_status})}
        return

    # ── Phase 4: Dual-channel fan-in loop ─────────────────────────────────
    merged: asyncio.Queue[str] = asyncio.Queue()

    async def _pump_lifecycle(src: asyncio.Queue[str]) -> None:
        """Relay Redis Pub/Sub lifecycle events into the merged queue."""
        try:
            while True:
                merged.put_nowait(await src.get())
        except asyncio.CancelledError:
            pass

    async def _pump_tokens(src: asyncio.Queue[str]) -> None:
        """Relay Redis Streams token events into the merged queue."""
        try:
            while True:
                merged.put_nowait(await src.get())
        except asyncio.CancelledError:
            pass

    async with (
        read_lifecycle(thread_id) as lifecycle_queue,
        read_stream(thread_id) as token_queue,
    ):
        lifecycle_pump = asyncio.create_task(_pump_lifecycle(lifecycle_queue))
        token_pump = asyncio.create_task(_pump_tokens(token_queue))

        # Post-subscribe re-check: closes the race window between
        # replay_existing() and the Pub/Sub subscription becoming active.
        # Deduplicate by task_id — never send the same started/completed twice.
        post_events, _ = await replay_existing(thread_id)
        new_post_count = 0
        for evt in post_events:
            try:
                task_id = json.loads(evt["data"]).get("task_id")
                if task_id and task_id in replayed_task_ids:
                    continue
            except Exception:  # noqa: BLE001
                pass
            yield evt
            new_post_count += 1
            await _register_started_watch(evt, thread_id, replayed_task_ids, "post")

        if replay_events or new_post_count:
            logger.debug(
                "[generator] replayed=%d post_new=%d thread_id=%s",
                len(replay_events), new_post_count, thread_id,
            )

        tokens_forwarded = 0
        tokens_suppressed = 0
        batches_processed = 0
        t_connect = time.perf_counter()
        t_audit = t_connect

        try:
            while True:
                # Fast-path: skip wait_for setup when items are already queued.
                raw, timed_out = await _next_event(merged)

                if timed_out:
                    if await request.is_disconnected():
                        break
                    recovered = await _run_drain_cycle(thread_id, merged)
                    if not recovered:
                        yield {"event": "ping", "data": "{}"}
                    continue

                # Batch-drain up to _MAX_BATCH items to reduce per-item overhead.
                batch: list[str] = [raw]
                for _ in range(_MAX_BATCH - 1):
                    try:
                        batch.append(merged.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                batches_processed += 1

                if await request.is_disconnected():
                    logger.debug("[generator] disconnected before batch thread_id=%s", thread_id)
                    await unregister_watch(thread_id)
                    break

                done = False
                for raw in batch:
                    payload = json.loads(raw)
                    event_type: str = payload.get("event", "message")

                    # Auto-advance watch on each new 'started' task so tokens
                    # flow for sequential pipelines without a manual PUT /watch.
                    if event_type == "started":
                        task_id = payload.get("task_id")
                        if task_id:
                            await register_watch(thread_id, task_id)
                            logger.debug(
                                "[generator] watch_live task_id=%d thread_id=%s",
                                task_id, thread_id,
                            )

                    if event_type == "query_status":
                        logger.info(
                            "[generator] query_status phase=%s thread_id=%s",
                            payload.get("phase"), thread_id,
                        )

                    # Suppress token events for tasks the client has not expanded.
                    # perf_token events always pass — they feed silent metrics.
                    if event_type == "token":
                        watched = await get_watched_task(thread_id)
                        if watched != payload.get("task_id"):
                            if tokens_suppressed == 0:
                                logger.debug(
                                    "[generator] first_suppression watched=%s task=%s thread_id=%s",
                                    watched, payload.get("task_id"), thread_id,
                                )
                            tokens_suppressed += 1
                            continue
                        tokens_forwarded += 1

                    # Pre-drain perf_token_batch frames before forwarding a perf
                    # terminal event.  The lifecycle channel (Pub/Sub) delivers
                    # perf_test_stopped/perf_test_complete faster than XREAD;
                    # drain trailing token frames first to avoid short counts.
                    if event_type in ("perf_test_stopped", "perf_test_complete"):
                        pre_items = await _drain_perf_tokens(merged, event_type, thread_id)
                        for item in pre_items:
                            yield {"event": "perf_token_batch", "data": item}
                            tokens_forwarded += 1

                    yield {"event": event_type, "data": raw}

                    # ACK lifecycle events so the drain cycle does not re-deliver.
                    if event_type in LIFECYCLE_EVENTS:
                        task_id_ack = payload.get("task_id")
                        await ack_pending_notify(thread_id, event_type, task_id_ack)
                        await ack_task_step(thread_id, task_id_ack, event_type)

                    if event_type == "done":
                        elapsed = time.perf_counter() - t_connect
                        logger.info(
                            "[generator] done status=%s fwd=%d sup=%d batches=%d elapsed=%.1fs thread_id=%s",
                            payload.get("status"),
                            tokens_forwarded, tokens_suppressed,
                            batches_processed, elapsed, thread_id,
                        )
                        await unregister_watch(thread_id)
                        done = True
                        # Do NOT break — finish the batch so any perf_token_batch
                        # events packed alongside `done` are also forwarded.

                # 10-second audit log.
                now = time.perf_counter()
                if now - t_audit >= 10.0:
                    logger.info(
                        "[generator] audit fwd=%d sup=%d batches=%d elapsed=%.1fs thread_id=%s",
                        tokens_forwarded, tokens_suppressed, batches_processed,
                        now - t_connect, thread_id,
                    )
                    t_audit = now

                if done:
                    # Post-drain: wait up to _PERF_DRAIN_WINDOW for any
                    # remaining perf_token_batch frames still in-flight on XREAD.
                    post_items = await _drain_perf_tokens_post_done(merged, thread_id)
                    for item in post_items:
                        yield {"event": "perf_token_batch", "data": item}
                        tokens_forwarded += 1
                    break

                # Yield event loop between batches so uvicorn can accept new
                # connections during high-throughput token delivery.
                await asyncio.sleep(0)

                if await request.is_disconnected():
                    logger.debug("[generator] disconnected thread_id=%s", thread_id)
                    await unregister_watch(thread_id)
                    break

        finally:
            lifecycle_pump.cancel()
            token_pump.cancel()
            await clear_pending_notify(thread_id)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _register_started_watch(
    evt: dict,
    thread_id: str,
    seen: set[int],
    phase: str,
) -> None:
    """If *evt* is a ``started`` event, add task_id to *seen* and register watch.

    Args:
        evt:       SSE event dict with ``"data"`` JSON payload.
        thread_id: LangGraph thread UUID.
        seen:      Set of already-replayed task_ids (mutated in place).
        phase:     Log label — ``"replay"`` or ``"post"``.
    """
    try:
        data = json.loads(evt["data"])
        if data.get("event") == "started":
            task_id = data.get("task_id")
            if task_id:
                seen.add(task_id)
                await register_watch(thread_id, task_id)
                logger.debug(
                    "[generator] watch_%s task_id=%d thread_id=%s",
                    phase, task_id, thread_id,
                )
    except Exception:  # noqa: BLE001
        pass


async def _next_event(merged: asyncio.Queue[str]) -> tuple[str, bool]:
    """Return ``(raw, timed_out)`` from *merged*.

    Fast-path bypasses ``wait_for`` overhead when items are already queued.

    Args:
        merged: Shared fan-in queue.

    Returns:
        ``(raw_json, False)`` on success, ``("", True)`` on ping timeout.

    Raises:
        asyncio.CancelledError: Propagated to cancel the generator cleanly.
        Exception: Any other queue error propagated to the main loop.
    """
    try:
        return merged.get_nowait(), False
    except asyncio.QueueEmpty:
        pass
    try:
        return await asyncio.wait_for(merged.get(), timeout=_PING_INTERVAL), False
    except asyncio.TimeoutError:
        return "", True


async def _run_drain_cycle(
    thread_id: str,
    merged: asyncio.Queue[str],
) -> bool:
    """Run the pending-notify drain cycle on ping timeout.

    Re-injects overdue lifecycle events into *merged* for processing in the
    next loop iteration.

    Args:
        thread_id: LangGraph thread UUID.
        merged:    Shared fan-in queue.

    Returns:
        ``True`` if any live entries were recovered (caller should ``continue``);
        ``False`` when only expired entries or nothing — caller emits a ping.
    """
    drain_entries = await drain_pending_notify(thread_id)
    live = [e for e in drain_entries if not e.expired]
    expired = [e for e in drain_entries if e.expired]

    for exp in expired:
        logger.warning(
            "[generator] drain_expired event=%s task_id=%s thread_id=%s",
            exp.event_type, exp.task_id, thread_id,
        )

    if live:
        logger.info(
            "[generator] drain_recovered live=%d expired=%d thread_id=%s",
            len(live), len(expired), thread_id,
        )
        for entry in live:
            merged.put_nowait(entry.raw)
            await increment_task_step_retry(thread_id, entry.task_id, entry.event_type)
        return True

    if expired:
        logger.info("[generator] drain_all_expired count=%d thread_id=%s", len(expired), thread_id)
    return False


async def _drain_perf_tokens(
    merged: asyncio.Queue[str],
    trigger_event: str,
    thread_id: str,
) -> list[str]:
    """Drain trailing ``perf_token_batch`` frames before a perf terminal event.

    The lifecycle channel (Pub/Sub) delivers ``perf_test_stopped`` /
    ``perf_test_complete`` faster than the Redis Streams XREAD cycle.  Without
    this drain the client closes the EventSource before the last token batch
    arrives, causing a short token count.

    Waits up to :data:`_PERF_DRAIN_WINDOW` seconds.  Non-token events are
    re-queued in *merged* for normal processing.

    Args:
        merged:        Shared fan-in queue.
        trigger_event: The perf terminal event that triggered this drain.
        thread_id:     For logging.

    Returns:
        List of raw JSON strings for ``perf_token_batch`` events to yield
        (in order) before the caller yields the trigger event.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + _PERF_DRAIN_WINDOW
    perf_items: list[str] = []
    requeue: list[str] = []

    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        try:
            item: str = await asyncio.wait_for(merged.get(), timeout=remaining)
        except asyncio.TimeoutError:
            break
        if json.loads(item).get("event") == "perf_token_batch":
            perf_items.append(item)
        else:
            requeue.append(item)

    for item in requeue:
        merged.put_nowait(item)

    if perf_items:
        logger.debug(
            "[generator] perf_pre_drain trigger=%s count=%d thread_id=%s",
            trigger_event, len(perf_items), thread_id,
        )
    return perf_items


async def _drain_perf_tokens_post_done(
    merged: asyncio.Queue[str],
    thread_id: str,
) -> list[str]:
    """Drain any remaining ``perf_token_batch`` frames after ``done``.

    ``done`` races ahead of the final XREAD cycle; wait up to
    :data:`_PERF_DRAIN_WINDOW` for trailing frames.  Non-perf events after
    ``done`` are silently discarded (``done`` is terminal).

    Args:
        merged:    Shared fan-in queue.
        thread_id: For logging.

    Returns:
        List of raw JSON strings for ``perf_token_batch`` events to yield.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + _PERF_DRAIN_WINDOW
    perf_items: list[str] = []

    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        try:
            extra: str = await asyncio.wait_for(merged.get(), timeout=remaining)
        except asyncio.TimeoutError:
            break
        if json.loads(extra).get("event") == "perf_token_batch":
            perf_items.append(extra)
        # Non-perf events after done are discarded (session is terminal).

    if perf_items:
        logger.debug(
            "[generator] perf_post_drain count=%d thread_id=%s",
            len(perf_items), thread_id,
        )
    return perf_items


__all__ = ["build_sse_generator"]
