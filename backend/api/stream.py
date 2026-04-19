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
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select, update
from sse_starlette.sse import EventSourceResponse

from backend.api.registry import running_tasks, is_task_active
from backend.db.postgres.engine import get_session_factory
from backend.db.postgres.listener import pg_listen
from backend.db.redis.subscriber import read_stream
from backend.graph.models import AgentTask
from backend.users.models import UserQuery

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stream", tags=["stream"])

# Maps thread_id → the single task_id the client wants token events for.
# None / absent = client is watching no task; token events are suppressed.
_watch_registry: dict[str, int] = {}


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
        _watch_registry.pop(thread_id, None)
        logger.debug(
            "[stream] watch_unregistered thread_id=%s",
            thread_id,
        )
    else:
        _watch_registry[thread_id] = body.task_id
        logger.debug(
            "[stream] watch_registered task_id=%d thread_id=%s",
            body.task_id,
            thread_id,
        )
    return {"thread_id": thread_id, "task_id": body.task_id}


async def _replay_existing(thread_id: str) -> tuple[list[dict], str]:
    """Load existing tasks and query status for late-connecting clients.

    Args:
        thread_id: The LangGraph thread UUID.

    Returns:
        A tuple of (replay_events, query_status) where replay_events is a list
        of SSE-ready dicts and query_status is the current ``user_queries.status``.
    """
    factory = get_session_factory()
    events: list[dict] = []
    query_status = "running"

    async with factory() as session:
        # Load completed/failed query state
        uq_row = await session.scalar(
            select(UserQuery).where(UserQuery.thread_id == thread_id)
        )
        if uq_row is not None:
            query_status = uq_row.status

        # Replay all recorded tasks as started + completed/failed pairs
        result = await session.execute(
            select(AgentTask)
            .where(AgentTask.thread_id == thread_id)
            .order_by(AgentTask.created_at)
        )
        tasks = result.scalars().all()

    for task in tasks:
        started_payload = json.dumps({
            "event": "started",
            "task_id": task.id,
            "node_name": task.node_name,
            "task_key": task.task_key,
        })
        events.append({"event": "started", "data": started_payload})

        if task.status in ("completed", "failed", "cancelled"):
            done_payload = json.dumps({
                "event": task.status,
                "task_id": task.id,
                "node_name": task.node_name,
                "task_key": task.task_key,
                "output": task.output if task.output else {},
            })
            events.append({"event": task.status, "data": done_payload})

    return events, query_status


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
        replay_events, query_status = await _replay_existing(thread_id)
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
                        _watch_registry[thread_id] = task_id
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

        # Orphaned query: DB says 'running' but no active task exists
        # (e.g. server restarted mid-query, or Celery worker was killed).
        # Performance-test orphans are silently cancelled; all other orphans
        # are marked failed so the client can exit the loading state.
        if not is_task_active(thread_id):
            factory = get_session_factory()
            async with factory() as session:
                uq = await session.scalar(
                    select(UserQuery).where(UserQuery.thread_id == thread_id)
                )
                is_perf_test = (
                    uq is not None
                    and uq.query.strip() == "DO STREAMING PERFORMANCE TEST NOW"
                )
                if is_perf_test:
                    logger.debug(
                        "[stream] perf-test orphan cancelled thread_id=%s", thread_id
                    )
                    await session.execute(
                        update(UserQuery)
                        .where(UserQuery.thread_id == thread_id)
                        .values(status="cancelled")
                    )
                else:
                    logger.warning(
                        "[stream] orphaned running query detected thread_id=%s", thread_id
                    )
                    await session.execute(
                        update(UserQuery)
                        .where(UserQuery.thread_id == thread_id)
                        .values(status="failed", error="Server restarted — query interrupted")
                    )
                await session.commit()
            final_status = "cancelled" if is_perf_test else "failed"
            yield {
                "event": "done",
                "data": json.dumps({"event": "done", "status": final_status}),
            }
            return

        # ── Dual-source fan-in ────────────────────────────────────────────
        # Open both channels concurrently.  A single merged asyncio.Queue is
        # used so the main loop does not need to select between two sources.
        merged: asyncio.Queue[str] = asyncio.Queue()

        async def _pump_pg(src: asyncio.Queue[str]) -> None:
            """Forward pg_notify lifecycle events into the merged queue."""
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

        async with pg_listen(thread_id) as pg_queue, read_stream(thread_id) as token_queue:
            pg_pump = asyncio.create_task(_pump_pg(pg_queue))
            token_pump = asyncio.create_task(_pump_tokens(token_queue))

            # Post-subscribe re-check: close the race window where `create_task`
            # committed to DB and fired pg_notify while `_replay_existing` was
            # running (before LISTEN was active).  Re-query once and emit any
            # tasks that were missed, auto-registering the watch so tokens flow.
            if not replay_events:
                post_events, _ = await _replay_existing(thread_id)
                for evt in post_events:
                    yield evt
                    try:
                        data = json.loads(evt["data"])
                        if data.get("event") == "started":
                            task_id = data.get("task_id")
                            if task_id:
                                _watch_registry[thread_id] = task_id
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
            _SUPPRESSED_YIELD_INTERVAL = 500
            _suppressed_since_yield = 0

            try:
                while True:
                    # ── Wait for next item from either source ─────────────
                    try:
                        raw: str = await asyncio.wait_for(merged.get(), timeout=25.0)
                    except asyncio.CancelledError:
                        logger.debug("[stream] generator cancelled thread_id=%s", thread_id)
                        break
                    except asyncio.TimeoutError:
                        if await request.is_disconnected():
                            break
                        yield {"event": "ping", "data": "{}"}
                        continue
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[stream] error thread_id=%s: %s", thread_id, exc)
                        break

                    # ── Batch-drain any additional queued items synchronously
                    batch: list[str] = [raw]
                    while True:
                        try:
                            batch.append(merged.get_nowait())
                        except asyncio.QueueEmpty:
                            break

                    batches_processed += 1

                    # ── Process batch ─────────────────────────────────────
                    done = False
                    for raw in batch:
                        payload = json.loads(raw)
                        event_type = payload.get("event", "message")

                        # Auto-register the watch from live 'started' events when
                        # no watch is set yet (covers the case where the client
                        # connects before tasks exist — the replay path covers the
                        # late-connect case).
                        if event_type == "started" and thread_id not in _watch_registry:
                            task_id = payload.get("task_id")
                            if task_id:
                                _watch_registry[thread_id] = task_id
                                logger.debug(
                                    "[stream] watch_auto_registered_live task_id=%d thread_id=%s",
                                    task_id, thread_id,
                                )

                        # Token events: suppress for tasks the client isn't watching.
                        # perf_token events bypass the watch registry — they are
                        # always forwarded for silent metric aggregation in the frontend.
                        if event_type == "token":
                            watched = _watch_registry.get(thread_id)
                            token_task_id = payload.get("task_id")
                            if watched != token_task_id:
                                if tokens_suppressed == 0:
                                    logger.debug(
                                        "[stream] first_suppression watched=%s payload_task_id=%s thread_id=%s",
                                        watched, token_task_id, thread_id,
                                    )
                                tokens_suppressed += 1
                                _suppressed_since_yield += 1
                                if _suppressed_since_yield >= _SUPPRESSED_YIELD_INTERVAL:
                                    _suppressed_since_yield = 0
                                    await asyncio.sleep(0)
                                continue
                            _suppressed_since_yield = 0
                            tokens_forwarded += 1

                        if await request.is_disconnected():
                            logger.debug(
                                "[stream] client disconnected before yield thread_id=%s",
                                thread_id,
                            )
                            _watch_registry.pop(thread_id, None)
                            done = True
                            break

                        yield {"event": event_type, "data": raw}

                        if event_type == "done":
                            elapsed = time.perf_counter() - t_connect
                            logger.info(
                                "[stream] done tokens_forwarded=%d suppressed=%d "
                                "batches=%d elapsed=%.1fs thread_id=%s",
                                tokens_forwarded, tokens_suppressed,
                                batches_processed, elapsed, thread_id,
                            )
                            _watch_registry.pop(thread_id, None)
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

                    if await request.is_disconnected():
                        logger.debug("[stream] client disconnected thread_id=%s", thread_id)
                        _watch_registry.pop(thread_id, None)
                        break
            finally:
                pg_pump.cancel()
                token_pump.cancel()

    return EventSourceResponse(_event_gen())
