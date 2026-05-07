"""Service logic for submitting a new user query.

Handles dedup guard and persistence, then emits the ``query_received`` event.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError

from backend.db import get_session_factory as _get_session_factory
from backend.db.redis.session.query_phase import set_query_phase
from backend.sse_notifications.thread import emit_query_received, emit_query_status
from backend.users.models import GuestUser, UserQuery
from backend.users.schemas import QueryRequest, QueryResponse

logger = logging.getLogger(__name__)

#: Active statuses — a query with one of these is still being processed.
_ACTIVE_STATUSES: tuple[str, ...] = ("received", "pending", "running")

#: Dedup window in seconds — duplicate submissions within this window are rejected.
_DEDUP_WINDOW_SECS: int = 60


async def submit_query(request: QueryRequest, user: GuestUser) -> QueryResponse:
    """Create a new query row and fire ``query_received``, or NACK a duplicate.

    If the same user submits the same query text while an existing row is still
    in ``received/pending/running`` state and was created within
    :data:`_DEDUP_WINDOW_SECS`, returns a NACK with ``status='cancelled'`` and
    the existing ``thread_id`` so the client can re-attach to the live stream.

    Args:
        request: Query payload with the user's natural-language question.
        user:    Authenticated guest user performing the submission.

    Returns:
        ``QueryResponse`` with ``status='received'`` on success, or
        ``status='cancelled'`` (NACK) for duplicate submissions.
    """
    factory = _get_session_factory()

    async with factory() as session:
        # ── Dedup guard ────────────────────────────────────────────────────
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=_DEDUP_WINDOW_SECS)
        existing = await session.scalar(
            select(UserQuery)
            .where(
                and_(
                    UserQuery.user_id == user.id,
                    UserQuery.query == request.query,
                    UserQuery.status.in_(list(_ACTIVE_STATUSES)),
                    UserQuery.created_at >= cutoff,
                )
            )
            .order_by(UserQuery.created_at.desc())
            .limit(1)
        )
        if existing:
            logger.info(
                "[submit] dedup_nack thread_id=%s user=%s",
                existing.thread_id,
                user.id,
            )
            return QueryResponse(
                thread_id=existing.thread_id,
                status="cancelled",
                error="duplicate_query",
            )

        # ── Persist new query with status='received' ────────────────────────
        thread_id = str(uuid.uuid4())
        session.add(
            UserQuery(
                thread_id=thread_id,
                user_id=user.id,
                query=request.query,
                status="received",
                extra={},
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            # Concurrent duplicate INSERT hit the unique index on another instance.
            await session.rollback()
            async with factory() as s2:
                dup = await s2.scalar(
                    select(UserQuery)
                    .where(
                        and_(
                            UserQuery.user_id == user.id,
                            UserQuery.query == request.query,
                            UserQuery.status.in_(list(_ACTIVE_STATUSES)),
                        )
                    )
                    .order_by(UserQuery.created_at.desc())
                    .limit(1)
                )
            if dup:
                logger.info(
                    "[submit] dedup_nack_concurrent thread_id=%s user=%s",
                    dup.thread_id,
                    user.id,
                )
                return QueryResponse(
                    thread_id=dup.thread_id,
                    status="cancelled",
                    error="duplicate_query",
                )
            raise

    logger.info(
        "[submit] query_received thread_id=%s query=%r",
        thread_id,
        request.query[:80],
    )

    # Store phase in Redis so late-connecting SSE clients can recover it.
    await set_query_phase(thread_id, "received")
    # Emit query_status for the query_status channel.
    await emit_query_status(thread_id, "received")
    # Emit query_received via Redis Pub/Sub + push to pending-notify store for retry.
    await emit_query_received(thread_id)

    return QueryResponse(thread_id=thread_id, status="received")
