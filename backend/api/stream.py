"""SSE streaming endpoint — dual-channel real-time graph task events.

Clients subscribe to ``GET /api/v1/stream/{thread_id}`` and receive
Server-Sent Events from two independent transmission channels:

  * **Redis Streams** (``tokens:<thread_id>``) — high-throughput LLM token
    events.  Each token is appended via ``XADD`` by the graph workers and
    consumed via ``XREAD BLOCK`` by the SSE generator.

  * **Redis Pub/Sub** (``lifecycle:<thread_id>``) — task lifecycle events
    (started / completed / failed / cancelled / done).  Events are published
    after the DB commit so the payload always reflects authoritative data.

The SSE generator fans in both channels into a single ``asyncio.Queue[str]``
and forwards events to the browser.

Event types (in the ``event`` field of each SSE frame):
  - ``connected``  — subscription confirmed
  - ``started``    — a sub-task began (task_id, node_name, task_key)
  - ``token``      — one LLM output token (from Redis Streams)
  - ``completed``  — a sub-task finished with final JSON output
  - ``failed``     — a sub-task failed
  - ``done``       — the entire query finished (status=completed|failed)
  - ``ping``       — keep-alive every 25 s (no data)

Heavy logic lives in dedicated streaming sub-modules:
  - ``backend.streaming.generator``         — SSE event generator
  - ``backend.streaming.status``            — session health query
  - ``backend.streaming.lifecycle``         — lifecycle constants and business helpers
  - ``backend.streaming.lifecycle.schemas`` — endpoint Pydantic models
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from backend.streaming.generator import build_sse_generator
from backend.streaming.lifecycle import (
    DoneAckRequest,
    DoneAckResponse,
    WatchTaskRequest,
    WatchTaskResponse,
    ack_done,
    register_watch,
    unregister_watch,
)
from backend.streaming.lifecycle.schemas import StreamingStatusResponse
from backend.streaming.status import get_session_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stream", tags=["stream"])


@router.put("/{thread_id}/watch", response_model=WatchTaskResponse, status_code=200)
async def watch_task(thread_id: str, body: WatchTaskRequest) -> WatchTaskResponse:
    """Register which task the client currently has expanded.

    The SSE generator for *thread_id* will only forward ``token`` events
    for the registered task; all other token events are suppressed.

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
    return WatchTaskResponse(thread_id=thread_id, task_id=body.task_id)


@router.get("/{thread_id}/status", response_model=StreamingStatusResponse)
async def get_streaming_status(thread_id: str) -> StreamingStatusResponse:
    """Return a health snapshot for the streaming session of *thread_id*.

    Called by the frontend when the SSE token stream appears to have stalled
    (no ``token`` event received for ≥ 5 seconds) while the session loading
    state is still active.

    If ``is_active`` is ``False`` and ``query_status`` is ``'running'`` the
    frontend should treat the session as orphaned (backend restarted without
    emitting ``done``).

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        :class:`~backend.streaming.lifecycle.schemas.StreamingStatusResponse`.
    """
    return await get_session_status(thread_id)


@router.post("/{thread_id}/done-ack", response_model=DoneAckResponse, status_code=200)
async def done_ack(thread_id: str, body: DoneAckRequest) -> DoneAckResponse:
    """Receive the client's done-acknowledgement for *thread_id*.

    Called by the frontend after the ``DoneConditionGuard`` has resolved —
    i.e. all drain conditions (every started task terminal, token count
    satisfied) have been met or the guard's drain window expired.

    Args:
        thread_id: LangGraph thread UUID.
        body:      ``{"status": "completed" | "failed" | "timeout" | ...}``.

    Returns:
        ``{"acknowledged": true, "thread_id": "<uuid>"}``
    """
    await ack_done(thread_id)
    logger.info("[stream] done_ack status=%s thread_id=%s", body.status, thread_id)
    return DoneAckResponse(acknowledged=True, thread_id=thread_id)


@router.get("/{thread_id}")
async def stream_thread(thread_id: str, request: Request) -> EventSourceResponse:
    """Subscribe to real-time task events for *thread_id* via SSE.

    On connect, replays all existing task rows from the DB so late-connecting
    clients see the full graph state.  If the query is already finished a
    ``done`` event is emitted and the stream closes immediately.

    Args:
        thread_id: The UUID returned when the query was submitted.
        request:   FastAPI request object (used to detect client disconnect).

    Returns:
        ``EventSourceResponse`` streaming JSON-encoded task events.
    """
    return EventSourceResponse(build_sse_generator(thread_id, request))
