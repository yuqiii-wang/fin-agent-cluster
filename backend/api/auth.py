"""FastAPI router for guest authentication and user history.

Mounted at ``/auth`` under the parent API router, so full paths are:

    POST /api/v1/auth/guest          — create or validate a guest session
    GET  /api/v1/auth/me/history     — list this user's thread history
    GET  /api/v1/auth/me/active      — fetch the most recent non-completed thread
"""

from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import desc, select

from backend.db.engine import get_session_factory
from backend.users.auth import ensure_guest
from backend.users.models import UserQuery
from backend.users.schemas import GuestAuthResponse, ThreadSummary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/guest", response_model=GuestAuthResponse)
async def guest_login(
    x_user_token: Annotated[Optional[str], Header(alias="X-User-Token")] = None,
) -> GuestAuthResponse:
    """Create a new guest session or revalidate an existing one.

    The client should pass its stored UUID via the ``X-User-Token`` header on
    subsequent visits.  If the token is absent or unrecognised a fresh guest
    account is created.

    Args:
        x_user_token: Optional bearer token from ``localStorage``.

    Returns:
        ``GuestAuthResponse`` with the canonical ``id`` to store in the browser.
    """
    user, is_new = await ensure_guest(x_user_token)
    return GuestAuthResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        email_verified=user.email_verified,
        avatar_url=user.avatar_url,
        auth_type=user.auth_type,
        is_new=is_new,
    )


@router.get("/me/history", response_model=list[ThreadSummary])
async def get_history(
    x_user_token: Annotated[str, Header(alias="X-User-Token")],
    limit: int = 20,
    offset: int = 0,
) -> list[ThreadSummary]:
    """Return this user's thread history, newest first.

    Args:
        x_user_token: Bearer token identifying the guest user.
        limit: Maximum number of records to return (default 20).
        offset: Pagination offset (default 0).

    Returns:
        List of ``ThreadSummary`` records ordered by ``created_at DESC``.

    Raises:
        HTTPException 401: If the token is missing or invalid.
    """
    user, _ = await ensure_guest(x_user_token)

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(UserQuery)
            .where(UserQuery.user_id == user.id)
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


@router.get("/me/active", response_model=Optional[ThreadSummary])
async def get_active_thread(
    x_user_token: Annotated[str, Header(alias="X-User-Token")],
) -> Optional[ThreadSummary]:
    """Return the user's most recent in-progress thread, if any.

    Used on page load to recover an unfinished session.  Returns ``null``
    when no running thread exists.

    Args:
        x_user_token: Bearer token identifying the guest user.

    Returns:
        A single ``ThreadSummary`` for the running thread, or ``null``.

    Raises:
        HTTPException 401: If the token is missing or invalid.
    """
    user, _ = await ensure_guest(x_user_token)

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(UserQuery)
            .where(
                UserQuery.user_id == user.id,
                UserQuery.status.in_(["pending", "running"]),
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
