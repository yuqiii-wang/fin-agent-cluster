"""Streaming lifecycle — orphaned query detection and recovery.

An *orphaned query* is a ``user_queries`` row with ``status='running'`` (or
``'received'``) that has no active asyncio task in the in-memory registry.
This typically happens when the server restarts mid-query.

:func:`handle_orphaned_query` detects and resolves this state by writing a
terminal status to the DB so the SSE generator can emit a ``done`` event and
close cleanly.

Race guard
----------
The function guards against the race where the graph runner completes and
commits a terminal status between the caller's ``SELECT`` and this module's
``UPDATE``.  The ``UPDATE`` is filtered to rows still in ``'running'`` or
``'received'``.  If it matches 0 rows, the status was already committed by
another writer and the function re-reads the DB to return the authoritative
current status.

Perf-test sessions
------------------
Performance-test queries (identified by the sentinel query text) are
*cancelled* rather than *failed* — they are ephemeral by design and the user
should be able to re-run them without seeing a failure indicator.
"""

from __future__ import annotations

import logging

from sqlalchemy import select, update

from backend.db.postgres.engine import get_session_factory
from backend.users.models import UserQuery

logger = logging.getLogger(__name__)

#: Sentinel query text identifying perf-test sessions.
_PERF_TEST_QUERY = "DO STREAMING PERFORMANCE TEST NOW"


async def handle_orphaned_query(thread_id: str) -> str:
    """Mark an orphaned running query as failed or cancelled.

    An orphaned query has ``status='running'`` but no active asyncio task in
    the in-memory registry — which happens when the server restarted mid-query.
    Performance-test queries are cancelled (not failed) as they are ephemeral.

    Guards against the race where the graph runner completes and clears the
    ``task_active`` Redis flag just before this function runs.  The UPDATE is
    filtered to only touch rows still in ``'running'`` or ``'received'`` state;
    if it matches 0 rows the query was already claimed by another writer (the
    runner itself) and the current DB status is returned instead.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        The effective terminal status: ``'cancelled'``, ``'failed'``,
        ``'completed'``, or whatever terminal value the DB already holds.
    """
    factory = get_session_factory()
    async with factory() as session:
        uq = await session.scalar(
            select(UserQuery).where(UserQuery.thread_id == thread_id)
        )
        if uq is None:
            return "failed"

        # Race guard: if the runner already committed a terminal status between
        # replay_existing() and is_task_active_any_instance(), do NOT overwrite
        # it.  Return the authoritative DB status so the SSE generator emits
        # the correct done event to the client.
        if uq.status in ("completed", "failed", "cancelled"):
            logger.debug(
                "[orphan] already_terminal status=%s thread_id=%s",
                uq.status, thread_id,
            )
            return uq.status

        is_perf_test = uq.query.strip() == _PERF_TEST_QUERY
        if is_perf_test:
            logger.debug("[orphan] perf-test cancelled thread_id=%s", thread_id)
            result = await session.execute(
                update(UserQuery)
                .where(
                    UserQuery.thread_id == thread_id,
                    UserQuery.status.in_(["running", "received"]),
                )
                .values(status="cancelled")
                .returning(UserQuery.thread_id)
            )
        else:
            logger.warning(
                "[orphan] running query detected — server may have restarted thread_id=%s",
                thread_id,
            )
            result = await session.execute(
                update(UserQuery)
                .where(
                    UserQuery.thread_id == thread_id,
                    UserQuery.status.in_(["running", "received"]),
                )
                .values(status="failed", error="Server restarted — query interrupted")
                .returning(UserQuery.thread_id)
            )
        claimed = result.fetchone() is not None
        await session.commit()

    if not claimed:
        # Another writer (the graph runner) claimed the terminal transition
        # between our SELECT and this UPDATE.  Re-read to return the true status.
        async with factory() as s2:
            uq2 = await s2.scalar(
                select(UserQuery).where(UserQuery.thread_id == thread_id)
            )
        current = uq2.status if uq2 is not None else "failed"
        logger.debug(
            "[orphan] update_noop current_status=%s thread_id=%s",
            current, thread_id,
        )
        return current

    return "cancelled" if is_perf_test else "failed"


__all__ = ["handle_orphaned_query"]
