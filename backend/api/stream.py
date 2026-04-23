"""SSE streaming endpoint — dual-channel real-time graph task events.

Clients subscribe to ``GET /api/v1/stream/{thread_id}`` and receive
Server-Sent Events from two independent transmission channels:

  * **Redis Streams** (``tokens:<thread_id>``) — high-throughput LLM token
    events.  Each token is appended via ``XADD`` by the graph workers and
    consumed via ``XREAD BLOCK`` by the SSE generator.

  * **PostgreSQL NOTIFY** (channel ``task_events:<thread_id>``) — task
    lifecycle events (started / completed / failed / cancelled / done).
    Notifications are fired **after** the DB commit so the payload always
    reflects authoritative, durable data.

The SSE generator fans in both queues into a single ``asyncio.Queue[str]``
and forwards events to the browser.

Event types (in the ``event`` field of each SSE frame):
  - ``connected``  — subscription confirmed
  - ``started``    — a sub-task began (includes task_id, node_name, task_key)
  - ``token``      — one LLM output token (from Redis Streams)
  - ``completed``  — a sub-task finished with final JSON output (from pg_notify)
  - ``failed``     — a sub-task failed (from pg_notify)
  - ``done``       — the entire query finished (status=completed|failed)
  - ``ping``       — keep-alive every 25 s (no data)

Business logic (watch registry, event replay, orphan detection) lives in
``backend.streaming.sse_session`` to keep this router thin.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from backend.api.registry import is_task_active, is_task_active_any_instance
from backend.db.postgres.engine import get_session_factory
from backend.db.redis.lifecycle_subscriber import read_lifecycle
from backend.db.redis.publisher import ack_pending_notify, clear_pending_notify, drain_pending_notify, get_last_token_ms_ago
from backend.db.redis.subscriber import read_stream
from backend.graph.models import AgentTask
from backend.sse_notifications.agent_tasks.ack import ack_task_step, increment_task_step_retry
from backend.streaming.sse_session import (
    LIFECYCLE_EVENTS,
    get_watched_task,
    handle_orphaned_query,
    is_thread_watching,
    register_watch,
    replay_existing,
    unregister_watch,
)
from backend.users.models import UserQuery

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stream", tags=["stream"])


class WatchTaskRequest(BaseModel):
    """Body for the watch endpoint.

    Attributes:
        task_id: The task the client has expanded (None to unwatch).
    """

    task_id: int | None = None


@router.put("/{thread_id}/watch", status_code=200)
async def watch_task(thread_id: str, body: WatchTaskRequest) -> dict:
    """Register which task the client currently has expanded.

    The SSE generator for *thread_id* will only forward ``token`` events
    for the registered task; all other token events are suppressed (the
    backend still processes and stores them).

    Args:
        thread_id: LangGraph thread UUID.
        body:      ``{"task_id": int | null}`` — the expanded task, or null
                   to unwatch (collapse all).

    Returns:
        Echo of the registered thread_id and task_id.
    """
    if body.task_id is None:
        await unregister_watch(thread_id)
    else:
        await register_watch(thread_id, body.task_id)
    return {"thread_id": thread_id, "task_id": body.task_id}


class RunningTaskInfo(BaseModel):
    """Minimal task info returned by the streaming-status endpoint.

    Attributes:
        task_id:   DB primary key of the task.
        task_key:  Dot-delimited task key, e.g. ``market_data_collector.fetch``.
        node_name: Graph node the task belongs to.
    """

    task_id: int
    task_key: str
    node_name: str


class StreamingStatusResponse(BaseModel):
    """Health snapshot for an active streaming session.

    Returned by ``GET /stream/{thread_id}/status``.  Intended to be polled by
    the frontend when no ``token`` SSE event has been received for ≥ 5 seconds
    while the session is still in loading state.

    Attributes:
        thread_id:          LangGraph thread UUID.
        query_status:       Current ``user_queries.status`` (``running``,
                            ``completed``, etc.).
        running_tasks:      Tasks whose DB status is still ``'running'``.
        last_token_ms_ago:  Milliseconds since the most-recent token was
                            published to Redis Streams; ``None`` if the stream
                            key no longer exists.
        is_active:          ``True`` if an asyncio.Task is registered in the
                            in-memory registry and has not finished.
    """

    thread_id: str
    query_status: str
    running_tasks: list[RunningTaskInfo]
    last_token_ms_ago: int | None
    is_active: bool


@router.get("/{thread_id}/status", response_model=StreamingStatusResponse)
async def get_streaming_status(thread_id: str) -> StreamingStatusResponse:
    """Return a health snapshot for the streaming session of *thread_id*.

    Called by the frontend when the SSE token stream appears to have stalled
    (no ``token`` event received for ≥ 5 seconds) while the session loading
    state is still active.  Provides diagnostics:

    * ``is_active`` — whether the backend asyncio.Task is still alive.
    * ``last_token_ms_ago`` — how recently the LLM was publishing tokens.
    * ``running_tasks`` — which DB tasks are still in ``'running'`` state.

    If ``is_active`` is ``False`` and ``query_status`` is ``'running'`` the
    frontend should treat the session as orphaned (backend restarted without
    emitting ``done``).

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        :class:`StreamingStatusResponse` with current streaming health data.
    """
    factory = get_session_factory()
    async with factory() as session:
        uq = await session.scalar(
            select(UserQuery).where(UserQuery.thread_id == thread_id)
        )
        query_status = uq.status if uq is not None else "unknown"

        result = await session.execute(
            select(AgentTask).where(
                AgentTask.thread_id == thread_id,
                AgentTask.status == "running",
            )
        )
        tasks = result.scalars().all()

    running = [
        RunningTaskInfo(task_id=t.id, task_key=t.task_key, node_name=t.node_name)
        for t in tasks
    ]
    last_token_ms_ago = await get_last_token_ms_ago(thread_id)
    active = await is_task_active_any_instance(thread_id)

    logger.debug(
        "[stream] status_check query_status=%s running_tasks=%d last_token_ms_ago=%s is_active=%s thread_id=%s",
        query_status, len(running), last_token_ms_ago, active, thread_id,
    )
    return StreamingStatusResponse(
        thread_id=thread_id,
        query_status=query_status,
        running_tasks=running,
        last_token_ms_ago=last_token_ms_ago,
        is_active=active,
    )


@router.get("/{thread_id}")
async def stream_thread(thread_id: str, request: Request) -> EventSourceResponse:
    """Subscribe to real-time task events for *thread_id* via SSE.

    On connect, replays all existing task rows from the DB so late-connecting
    clients see the full graph state.  If the query is already finished a
    ``done`` event is emitted and the stream closes immediately.  Otherwise,
    opens a PostgreSQL ``LISTEN`` subscription for live updates.

    Args:
        thread_id: The UUID returned when the query was submitted.
        request:   FastAPI request object (used to detect client disconnect).

    Returns:
        ``EventSourceResponse`` streaming JSON-encoded task events.
    """

    async def _event_gen() -> AsyncGenerator[dict, None]:
        logger.debug(
            "[stream] client_connected thread_id=%s",
            thread_id,
        )
        yield {
            "event": "connected",
            "data": json.dumps({"thread_id": thread_id}),
        }

        # Replay past events for late-connecting clients
        replay_events, query_status = await replay_existing(thread_id)
        for evt in replay_events:
            if await request.is_disconnected():
                logger.debug("[stream] client disconnected during replay thread_id=%s", thread_id)
                return
            yield evt
            # Auto-register watch for the last started task so tokens flow for
            # late-connecting clients (mirrors the post-subscribe re-check path).
            try:
                data = json.loads(evt["data"])
                if data.get("event") == "started":
                    task_id = data.get("task_id")
                    if task_id:
                        await register_watch(thread_id, task_id)
                        logger.debug(
                            "[stream] watch_auto_registered_replay task_id=%d thread_id=%s",
                            task_id, thread_id,
                        )
            except Exception:  # noqa: BLE001
                pass

        # If already finished, emit done and close
        if query_status in ("completed", "failed", "cancelled"):
            yield {
                "event": "done",
                "data": json.dumps({"event": "done", "status": query_status}),
            }
            return

        # 'received' = query persisted but awaiting client ACK before the graph
        # starts.  The replay path already emitted query_received; the live loop
        # below will serve drain-cycle retries.  Skip orphan detection entirely.
        if query_status != "received" and not await is_task_active_any_instance(thread_id):
            final_status = await handle_orphaned_query(thread_id)
            yield {
                "event": "done",
                "data": json.dumps({"event": "done", "status": final_status}),
            }
            return

        # ── Dual-source fan-in ────────────────────────────────────────────
        # Open both channels concurrently.  A single merged asyncio.Queue is
        # used so the main loop does not need to select between two sources.
        merged: asyncio.Queue[str] = asyncio.Queue()

        async def _pump_lifecycle(src: asyncio.Queue[str]) -> None:
            """Forward lifecycle events from Redis Pub/Sub into the merged queue."""
            try:
                while True:
                    raw = await src.get()
                    merged.put_nowait(raw)
            except asyncio.CancelledError:
                pass

        async def _pump_tokens(src: asyncio.Queue[str]) -> None:
            """Forward Redis Stream token events into the merged queue."""
            try:
                while True:
                    raw = await src.get()
                    merged.put_nowait(raw)
            except asyncio.CancelledError:
                pass

        async with read_lifecycle(thread_id) as lifecycle_queue, read_stream(thread_id) as token_queue:
            lifecycle_pump = asyncio.create_task(_pump_lifecycle(lifecycle_queue))
            token_pump = asyncio.create_task(_pump_tokens(token_queue))

            # Post-subscribe re-check: close the race window where `create_task`
            # committed to DB and fired pg_notify while `replay_existing` was
            # running (before LISTEN was active).  Re-query once and emit any
            # tasks that were missed, auto-registering the watch so tokens flow.
            if not replay_events:
                post_events, _ = await replay_existing(thread_id)
                for evt in post_events:
                    yield evt
                    try:
                        data = json.loads(evt["data"])
                        if data.get("event") == "started":
                            task_id = data.get("task_id")
                            if task_id:
                                await register_watch(thread_id, task_id)
                                logger.debug(
                                    "[stream] watch_auto_registered task_id=%d thread_id=%s",
                                    task_id, thread_id,
                                )
                    except Exception:  # noqa: BLE001
                        pass
            else:
                logger.debug(
                    "[stream] replayed_events=%d thread_id=%s",
                    len(replay_events),
                    thread_id,
                )

            tokens_forwarded = 0
            tokens_suppressed = 0
            batches_processed = 0
            t_connect = time.perf_counter()
            t_audit = t_connect
            # Cap batch size so the event loop yields between batches and
            # can accept new HTTP requests (e.g. POST /users/query) even
            # during high-throughput perf-test token delivery.
            _MAX_BATCH = 50

            try:
                while True:
                    # ── Wait for next item from either source ─────────────
                    # Fast-path: skip wait_for() timer setup when items are
                    # already queued (common during active token streaming).
                    _timed_out = False
                    try:
                        raw: str = merged.get_nowait()
                    except asyncio.QueueEmpty:
                        try:
                            raw = await asyncio.wait_for(merged.get(), timeout=25.0)
                        except asyncio.CancelledError:
                            logger.debug("[stream] generator cancelled thread_id=%s", thread_id)
                            break
                        except asyncio.TimeoutError:
                            _timed_out = True
                            raw = ""  # type: ignore[assignment]
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("[stream] error thread_id=%s: %s", thread_id, exc)
                            break

                    if _timed_out:
                        if await request.is_disconnected():
                            break
                        # Drain unacked pg_notify events — recovers any lifecycle
                        # notifications (including ``done``) that were fired but
                        # whose PG LISTEN delivery was lost (e.g. momentary
                        # connection drop or LISTEN/NOTIFY gap).
                        drain_entries = await drain_pending_notify(thread_id)
                        live_entries = [e for e in drain_entries if not e.expired]
                        expired_entries = [e for e in drain_entries if e.expired]
                        for exp in expired_entries:
                            logger.warning(
                                "[stream] drain_expired event=%s task_id=%s age>10min thread_id=%s",
                                exp.event_type, exp.task_id, thread_id,
                            )
                        if live_entries:
                            logger.info(
                                "[stream] drain_pending recovered live=%d expired=%d thread_id=%s",
                                len(live_entries), len(expired_entries), thread_id,
                            )
                            for entry in live_entries:
                                merged.put_nowait(entry.raw)
                                # Track retry in DB for task-level lifecycle events.
                                await increment_task_step_retry(entry.task_id, entry.event_type)
                            continue
                        if drain_entries and not live_entries:
                            # All recovered entries were expired — stop retrying.
                            logger.info(
                                "[stream] drain_all_expired count=%d thread_id=%s",
                                len(expired_entries), thread_id,
                            )
                        yield {"event": "ping", "data": "{}"}
                        continue

                    # ── Batch-drain up to _MAX_BATCH additional queued items.
                    # Capping prevents long uninterrupted bursts that would
                    # starve the event loop and block new request acceptance.
                    batch: list[str] = [raw]
                    for _ in range(_MAX_BATCH - 1):
                        try:
                            batch.append(merged.get_nowait())
                        except asyncio.QueueEmpty:
                            break

                    batches_processed += 1

                    # ── Process batch ─────────────────────────────────────
                    # Check disconnect ONCE per batch rather than per item.
                    # is_disconnected() creates an anyio cancel scope + ASGI
                    # receive call on every invocation while connected; calling
                    # it per-token multiplies the overhead by batch size.
                    if await request.is_disconnected():
                        logger.debug(
                            "[stream] client disconnected before batch thread_id=%s",
                            thread_id,
                        )
                        await unregister_watch(thread_id)
                        break

                    done = False
                    for raw in batch:
                        payload = json.loads(raw)
                        event_type = payload.get("event", "message")

                        # Auto-register the watch from live 'started' events when
                        # no watch is set yet (covers the case where the client
                        # connects before tasks exist — the replay path covers the
                        # late-connect case).
                        if event_type == "started" and not await is_thread_watching(thread_id):
                            task_id = payload.get("task_id")
                            if task_id:
                                await register_watch(thread_id, task_id)
                                logger.debug(
                                    "[stream] watch_auto_registered_live task_id=%d thread_id=%s",
                                    task_id, thread_id,
                                )

                        if event_type == "query_status":
                            logger.info(
                                "[stream] query_status_recv phase=%s thread_id=%s",
                                payload.get("phase"),
                                thread_id,
                            )

                        # Token events: suppress for tasks the client isn't watching.
                        # perf_token events bypass the watch registry — they are
                        # always forwarded for silent metric aggregation in the frontend.
                        if event_type == "token":
                            watched = await get_watched_task(thread_id)
                            token_task_id = payload.get("task_id")
                            if watched != token_task_id:
                                if tokens_suppressed == 0:
                                    logger.debug(
                                        "[stream] first_suppression watched=%s payload_task_id=%s thread_id=%s",
                                        watched, token_task_id, thread_id,
                                    )
                                tokens_suppressed += 1
                                continue
                            tokens_forwarded += 1

                        yield {"event": event_type, "data": raw}

                        # Ack delivery of lifecycle events so the pending-notify
                        # store knows they were received and won't re-deliver them
                        # on the next drain cycle.  Also persist the ack to the
                        # streaming audit log.
                        if event_type in LIFECYCLE_EVENTS:
                            task_id_ack = payload.get("task_id")  # None for "done"
                            await ack_pending_notify(thread_id, event_type, task_id_ack)
                            await ack_task_step(task_id_ack, event_type)

                        if event_type == "done":
                            elapsed = time.perf_counter() - t_connect
                            logger.info(
                                "[stream] done status=%s tokens_forwarded=%d suppressed=%d "
                                "batches=%d elapsed=%.1fs thread_id=%s",
                                payload.get("status"),
                                tokens_forwarded, tokens_suppressed,
                                batches_processed, elapsed, thread_id,
                            )
                            await unregister_watch(thread_id)
                            done = True
                            break

                    # Audit log every 10 seconds
                    now = time.perf_counter()
                    if now - t_audit >= 10.0:
                        logger.info(
                            "[stream] audit_10s tokens_fwd=%d suppressed=%d batches=%d "
                            "elapsed=%.1fs thread_id=%s",
                            tokens_forwarded, tokens_suppressed, batches_processed,
                            now - t_connect, thread_id,
                        )
                        t_audit = now

                    if done:
                        break

                    # Yield to the event loop between batches so the uvicorn
                    # accept loop can handle new HTTP connections ("add requests")
                    # even when many SSE streams are actively forwarding tokens.
                    await asyncio.sleep(0)

                    if await request.is_disconnected():
                        logger.debug("[stream] client disconnected thread_id=%s", thread_id)
                        await unregister_watch(thread_id)
                        break
            finally:
                lifecycle_pump.cancel()
                token_pump.cancel()
                # Clear any remaining pending-notify entries so they don't
                # accumulate in Redis after the SSE session ends cleanly.
                await clear_pending_notify(thread_id)

    return EventSourceResponse(_event_gen())
