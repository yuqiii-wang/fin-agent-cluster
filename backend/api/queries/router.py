"""backend.api.queries.router — user query history and lookup endpoints.

Non-streaming, plain HTTP endpoints for querying thread records.
These complement the streaming SSE flow in ``backend.api.threads``.

Routes
------
    GET  /api/v1/queries                      — paginated query history for the caller
    GET  /api/v1/queries/active               — most recent in-progress thread
    GET  /api/v1/queries/{thread_id}          — single thread status
    DELETE /api/v1/queries/{thread_id}        — cancel and remove a thread
"""

from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Header, Query

from backend.auth.guest import ensure_guest
from backend.users.queries import cancel_query, get_query_status, submit_query
from backend.users.schemas import QueryRequest, QueryResponse, ThreadSummary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/queries", tags=["queries"])


@router.post("", response_model=QueryResponse, status_code=201)
async def submit_query_endpoint(
    body: QueryRequest,
    x_user_token: Annotated[str, Header(alias="X-User-Token")],
) -> QueryResponse:
    """Submit a new analysis query and return its initial status.

    Creates a row in ``fin_agents.user_queries`` with ``status='received'``.
    The graph run begins after the frontend ACKs via
    ``POST /threads/{thread_id}/ack``.

    Args:
        body:         JSON payload with ``query`` string.
        x_user_token: Guest bearer token from ``localStorage``.

    Returns:
        :class:`QueryResponse` with ``status='received'`` and the new ``thread_id``.
    """
    user, _ = await ensure_guest(x_user_token)
    return await submit_query(body, user)


@router.get("/list", response_model=list[ThreadSummary])
async def list_queries(
    x_user_token: Annotated[str, Header(alias="X-User-Token")],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[ThreadSummary]:
    """Return the authenticated user's query history, newest first.

    Args:
        x_user_token: Guest bearer token from ``localStorage``.
        limit:        Max records to return (1–100, default 20).
        offset:       Pagination offset (default 0).

    Returns:
        List of :class:`ThreadSummary` ordered by ``created_at DESC``.
    """
    from sqlalchemy import desc, select
    from backend.db.postgres.engine import get_read_session_factory
    from backend.users.models import UserQuery

    user, _ = await ensure_guest(x_user_token)
    factory = get_read_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(UserQuery)
            .where(UserQuery.user_id == str(user.id))
            .order_by(desc(UserQuery.created_at))
            .limit(limit)
            .offset(offset)
        )
        rows = result.scalars().all()

    return [
        ThreadSummary(
            thread_id=r.thread_id,
            query=r.query,
            status=r.status,
            created_at=r.created_at,
            completed_at=r.completed_at,
            answer=r.answer,
        )
        for r in rows
    ]


@router.get("/active", response_model=Optional[ThreadSummary])
async def get_active_query(
    x_user_token: Annotated[str, Header(alias="X-User-Token")],
) -> Optional[ThreadSummary]:
    """Return the user's most recent in-progress query thread, or ``null``.

    Args:
        x_user_token: Guest bearer token from ``localStorage``.

    Returns:
        :class:`ThreadSummary` for the running thread, or ``null``.
    """
    from sqlalchemy import desc, select
    from backend.db.postgres.engine import get_session_factory
    from backend.users.models import UserQuery

    user, _ = await ensure_guest(x_user_token)
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(UserQuery)
            .where(
                UserQuery.user_id == str(user.id),
                UserQuery.status.in_(["received", "running"]),
            )
            .order_by(desc(UserQuery.created_at))
            .limit(1)
        )
        row = result.scalar_one_or_none()

    if not row:
        return None

    return ThreadSummary(
        thread_id=row.thread_id,
        query=row.query,
        status=row.status,
        created_at=row.created_at,
        completed_at=row.completed_at,
        answer=row.answer,
    )


@router.get("/{thread_id}", response_model=QueryResponse)
async def get_query(thread_id: str) -> QueryResponse:
    """Return the full status of a single query thread.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        :class:`QueryResponse` with the latest DB state.
    """
    return await get_query_status(thread_id)


@router.delete("/{thread_id}", response_model=QueryResponse)
async def cancel_and_remove_query(
    thread_id: str,
    x_user_token: Annotated[str, Header(alias="X-User-Token")],
) -> QueryResponse:
    """Cancel a running thread on behalf of the authenticated user.

    Args:
        thread_id:    LangGraph thread UUID.
        x_user_token: Guest bearer token (used to validate ownership).

    Returns:
        Updated :class:`QueryResponse` with ``status='cancelled'``.
    """
    await ensure_guest(x_user_token)
    return await cancel_query(thread_id, reason="user")


__all__ = ["router"]
