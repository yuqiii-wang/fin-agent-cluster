"""SSE streaming endpoint — real-time graph task events via PostgreSQL NOTIFY.

Clients subscribe to ``GET /api/v1/stream/{thread_id}`` and receive
Server-Sent Events as each graph node starts tasks, emits LLM tokens,
and completes work.

Event types (in the ``event`` field of each SSE frame):
  - ``connected``  — subscription confirmed
  - ``started``    — a sub-task began (includes task_id, node_name, task_key)
  - ``token``      — one LLM output token
  - ``completed``  — a sub-task finished (includes short detail)
  - ``failed``     — a sub-task failed
  - ``done``       — the entire query finished (status=completed|failed)
  - ``ping``       — keep-alive every 25 s (no data)
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select, update
from sse_starlette.sse import EventSourceResponse

from backend.api.registry import running_tasks
from backend.db.engine import get_session_factory
from backend.db.streaming import listen
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
    else:
        _watch_registry[thread_id] = body.task_id
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

        # If already finished, emit done and close
        if query_status in ("completed", "failed", "cancelled"):
            yield {
                "event": "done",
                "data": json.dumps({"event": "done", "status": query_status}),
            }
            return

        # Orphaned query: DB says 'running' but no asyncio task is alive
        # (e.g. server restarted mid-query).  Mark failed so the client
        # can exit the loading state instead of hanging forever.
        if thread_id not in running_tasks:
            logger.warning("[stream] orphaned running query detected thread_id=%s", thread_id)
            factory = get_session_factory()
            async with factory() as session:
                await session.execute(
                    update(UserQuery)
                    .where(UserQuery.thread_id == thread_id)
                    .values(status="failed", error="Server restarted — query interrupted")
                )
                await session.commit()
            yield {
                "event": "done",
                "data": json.dumps({"event": "done", "status": "failed"}),
            }
            return

        async with listen(thread_id) as queue:
            while True:
                if await request.is_disconnected():
                    logger.debug("[stream] client disconnected thread_id=%s", thread_id)
                    _watch_registry.pop(thread_id, None)
                    break
                try:
                    raw: str = await asyncio.wait_for(queue.get(), timeout=25.0)
                    payload = json.loads(raw)
                    event_type = payload.get("event", "message")

                    # Suppress token events for tasks the client isn't watching.
                    # The backend still processes and stores all tokens; we only
                    # skip the SSE forward when the panel is collapsed.
                    if event_type == "token":
                        watched = _watch_registry.get(thread_id)
                        if watched != payload.get("task_id"):
                            continue

                    if await request.is_disconnected():
                        logger.debug("[stream] client disconnected before yield thread_id=%s", thread_id)
                        break

                    yield {"event": event_type, "data": raw}
                    if event_type == "done":
                        _watch_registry.pop(thread_id, None)
                        break
                except asyncio.CancelledError:
                    logger.debug("[stream] generator cancelled thread_id=%s", thread_id)
                    break
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield {"event": "ping", "data": "{}"}
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[stream] error thread_id=%s: %s", thread_id, exc)
                    break

    return EventSourceResponse(_event_gen())
