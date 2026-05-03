"""api.auth.router — FastAPI router for authentication and Centrifugo bootstrap.

Mounted at ``/auth`` under the parent API router.  Full paths:

    POST /api/v1/auth/guest                         — create / validate a guest session
    GET  /api/v1/auth/me/history                    — list this user's thread history
    GET  /api/v1/auth/me/active                     — most recent non-completed thread
    GET  /api/v1/auth/centrifugo/token?thread_id=   — Centrifugo connection + subscription JWTs
"""

from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import desc, select

from backend.auth.guest import ensure_guest
from backend.auth.jwt import make_connection_token, make_subscription_token
from backend.auth.schemas import CentrifugoTokenResponse
from backend.centrifugo.client import get_shard_index
from backend.config import get_settings
from backend.db.postgres.engine import get_session_factory
from backend.users.models import UserQuery
from backend.users.schemas import GuestAuthResponse, ThreadSummary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Guest auth ────────────────────────────────────────────────────────────────


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


# ── Centrifugo token bootstrap ────────────────────────────────────────────────


@router.get("/centrifugo/token", response_model=CentrifugoTokenResponse)
async def get_centrifugo_token(
    thread_id: str,
    x_user_token: Annotated[str, Header(alias="X-User-Token")],
) -> CentrifugoTokenResponse:
    """Return Centrifugo connection and subscription tokens for *thread_id*.

    The frontend uses these tokens to establish a WebSocket connection to the
    correct Centrifugo shard and subscribe to the ``thread:{thread_id}``
    channel.

    Args:
        thread_id:     LangGraph thread UUID to subscribe to.
        x_user_token:  Guest-auth bearer token from ``localStorage``.

    Returns:
        ``CentrifugoTokenResponse`` with ``ws_url``, ``connection_token``,
        ``subscription_token``, ``shard_index``, and ``channel``.

    Raises:
        HTTPException 401: If ``x_user_token`` is invalid.
    """
    settings = get_settings()
    user, _ = await ensure_guest(x_user_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid user token")

    user_id = str(user.id)
    secret = settings.CENTRIFUGO_SECRET
    shard = get_shard_index(thread_id)
    channel = f"thread:{thread_id}"

    ws_url = f"{settings.CENTRIFUGO_PUBLIC_BASE}/centrifugo-{shard}/connection/websocket"
    connection_token = make_connection_token(user_id, secret)
    subscription_token = make_subscription_token(user_id, channel, secret)

    logger.debug(
        "[api.auth] centrifugo token issued user_id=%s thread_id=%s shard=%d",
        user_id,
        thread_id,
        shard,
    )
    return CentrifugoTokenResponse(
        ws_url=ws_url,
        connection_token=connection_token,
        subscription_token=subscription_token,
        shard_index=shard,
        channel=channel,
    )
