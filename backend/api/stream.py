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
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from backend.db.engine import get_session_factory
from backend.db.streaming import listen
from backend.graph.models import AgentTask
from backend.users.models import UserQuery

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stream", tags=["stream"])


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

        if task.status in ("completed", "failed"):
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
            yield evt

        # If already finished, emit done and close
        if query_status in ("completed", "failed"):
            yield {
                "event": "done",
                "data": json.dumps({"event": "done", "status": query_status}),
            }
            return

        async with listen(thread_id) as queue:
            while True:
                if await request.is_disconnected():
                    logger.debug("[stream] client disconnected thread_id=%s", thread_id)
                    break
                try:
                    raw: str = await asyncio.wait_for(queue.get(), timeout=25.0)
                    payload = json.loads(raw)
                    event_type = payload.get("event", "message")
                    yield {"event": event_type, "data": raw}
                    if event_type == "done":
                        break
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[stream] error thread_id=%s: %s", thread_id, exc)
                    break

    return EventSourceResponse(_event_gen())
