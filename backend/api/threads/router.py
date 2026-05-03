"""FastAPI router for thread inspection and event management.

Provides read and event endpoints that operate **without** triggering a
LangGraph graph run.  All writes are direct DB updates; events are published
directly to Centrifugo.

Endpoints
---------
GET  /api/v1/threads                              — list threads with pagination
GET  /api/v1/threads/{thread_id}/llm-responses   — LLM completion records
GET  /api/v1/threads/{thread_id}/state           — LangGraph checkpoint state
POST /api/v1/threads/{thread_id}/status          — update DB status + optional event
POST /api/v1/threads/{thread_id}/events/emit     — publish lifecycle event to channel
POST /api/v1/threads/{thread_id}/events/resync   — re-emit current state to clients
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Header, Query

from backend.users.auth import ensure_guest
from backend.users.queries.threads import (
    emit_thread_event,
    get_thread_llm_responses,
    get_thread_state,
    list_threads,
    resync_thread,
    update_thread_status,
)
from backend.users.schemas import (
    EmitEventRequest,
    EmitEventResponse,
    LlmResponseList,
    ResyncResponse,
    ThreadListResponse,
    ThreadStateResponse,
    UpdateThreadStatusRequest,
    UpdateThreadStatusResponse,
)

router = APIRouter(prefix="/threads", tags=["threads"])


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=ThreadListResponse)
async def list_threads_route(
    x_user_token: Annotated[str, Header(alias="X-User-Token")],
    status: Optional[str] = Query(
        default=None,
        description="Comma-separated status values to filter on, e.g. 'running,completed'.",
    ),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ThreadListResponse:
    """Return a paginated list of query threads for the authenticated user.

    Does not trigger any graph execution — reads directly from
    ``fin_agents.user_queries``.

    Args:
        x_user_token: Bearer token identifying the user.
        status:       Optional comma-separated status filter.
        limit:        Page size (1–100, default 20).
        offset:       Row offset (default 0).

    Returns:
        :class:`~backend.users.schemas.ThreadListResponse`.
    """
    user, _ = await ensure_guest(x_user_token)
    return await list_threads(user_id=user.id, status=status, limit=limit, offset=offset)


@router.get("/{thread_id}/llm-responses", response_model=LlmResponseList)
async def get_llm_responses_route(
    thread_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> LlmResponseList:
    """Return LLM completion records for *thread_id* from DB.

    Reads ``fin_agents.llm_responses`` — no graph execution triggered.

    Args:
        thread_id: LangGraph thread UUID.
        limit:     Max records (1–200, default 50).
        offset:    Row offset for pagination.

    Returns:
        :class:`~backend.users.schemas.LlmResponseList`.
    """
    return await get_thread_llm_responses(thread_id, limit=limit, offset=offset)


@router.get("/{thread_id}/state", response_model=ThreadStateResponse)
async def get_thread_state_route(thread_id: str) -> ThreadStateResponse:
    """Return the latest LangGraph checkpoint state for *thread_id*.

    Uses ``CompiledStateGraph.aget_state`` which reads from the PostgreSQL
    checkpointer without executing any graph nodes.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        :class:`~backend.users.schemas.ThreadStateResponse` with ``state``
        dict and ``checkpoint_id``.  ``state`` is empty when no checkpoint
        exists yet.
    """
    return await get_thread_state(thread_id)


# ---------------------------------------------------------------------------
# Write / event endpoints (no graph run)
# ---------------------------------------------------------------------------


@router.post("/{thread_id}/status", response_model=UpdateThreadStatusResponse)
async def update_thread_status_route(
    thread_id: str,
    body: UpdateThreadStatusRequest,
    x_user_token: Annotated[str, Header(alias="X-User-Token")],
) -> UpdateThreadStatusResponse:
    """Update a thread's status in DB without triggering a graph run.

    Writes the new status (and optional error) to ``fin_agents.user_queries``
    and — when ``emit_event`` is ``True`` — publishes a ``query_status``
    Centrifugo event so subscribed clients reflect the change immediately.

    Args:
        thread_id: LangGraph thread UUID.
        body:      ``{status, error?, emit_event?}``
        x_user_token: Authenticating user token.

    Returns:
        :class:`~backend.users.schemas.UpdateThreadStatusResponse`.
    """
    await ensure_guest(x_user_token)
    return await update_thread_status(
        thread_id,
        status=body.status,
        error=body.error,
        emit_event=body.emit_event,
    )


@router.post("/{thread_id}/events/emit", response_model=EmitEventResponse)
async def emit_event_route(
    thread_id: str,
    body: EmitEventRequest,
    x_user_token: Annotated[str, Header(alias="X-User-Token")],
) -> EmitEventResponse:
    """Publish a lifecycle event to the thread's Centrifugo channel.

    Does **not** modify any database rows.  Use this to replay events to
    reconnecting clients or to inject synthetic events for debugging/testing.

    ``event`` must be a lifecycle event type — high-frequency stream events
    (``token``, ``perf_token``) are rejected.

    Args:
        thread_id: LangGraph thread UUID.
        body:      ``{event, payload?}``
        x_user_token: Authenticating user token.

    Returns:
        :class:`~backend.users.schemas.EmitEventResponse`.
    """
    await ensure_guest(x_user_token)
    return await emit_thread_event(thread_id, event=body.event, payload=body.payload)


@router.post("/{thread_id}/events/resync", response_model=ResyncResponse)
async def resync_thread_route(
    thread_id: str,
    x_user_token: Annotated[str, Header(alias="X-User-Token")],
) -> ResyncResponse:
    """Re-emit current thread and task states as Centrifugo events.

    Reads the latest status of the thread and all its tasks from DB and
    publishes one ``query_status`` event plus one lifecycle event per task.
    Intended for clients that reconnect mid-session and need to rebuild
    their local state without replaying the full Centrifugo channel history.

    Args:
        thread_id: LangGraph thread UUID.
        x_user_token: Authenticating user token.

    Returns:
        :class:`~backend.users.schemas.ResyncResponse` with count of events
        emitted.
    """
    await ensure_guest(x_user_token)
    return await resync_thread(thread_id)
