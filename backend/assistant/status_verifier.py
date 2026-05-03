"""Assistant status verifier — background task that re-delivers unACKed
query-status lifecycle events to Centrifugo.

When the runner publishes a ``query_status`` event (received / preparing /
ingesting / digesting), it records the phase in the Redis
``query_status_ack:{thread_id}`` hash as ``is_ack=False``.  The frontend ACKs
the phase via ``POST /stream/{thread_id}/status-ack`` after processing the
Centrifugo publication.

This verifier runs on every assistant instance and periodically:
1. Queries the DB for queries still in ``received`` or ``running`` status.
2. Checks which phases have not been acknowledged in Redis.
3. Re-publishes unACKed phases via Centrifugo so connected clients
   receive them again (e.g. after a brief WS reconnect outside the 600s
   Centrifugo history window, or if the original event was lost in a
   transient WS glitch).

Design notes:
- The assistant is used because runner instances are occupied with graph
  execution; assistant instances have spare capacity for housekeeping.
- Re-publishing a phase already in Centrifugo history adds a duplicate entry
  but clients guard against duplicate ``query_status`` events via the monotonic
  status progression (``onQueryStatus`` only advances, never regresses).
- Configurable via :attr:`~backend.config.Settings.STATUS_VERIFIER_INTERVAL_SECS`
  and :attr:`~backend.config.Settings.STATUS_VERIFIER_LOOKBACK_SECS`.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select

from backend.config import get_settings
from backend.db import get_session_factory
from backend.db.redis.session.query_status_ack_store import (
    get_stream_id_for_thread,
    get_unacked_phases,
    increment_phase_retry,
)
from backend.sse_notifications.channel import publish_thread_lifecycle
from backend.users.models import UserQuery

logger = logging.getLogger(__name__)

#: DB statuses that indicate a query might still be waiting for the client
#: to receive lifecycle events.
_ACTIVE_STATUSES = ("received", "running")


async def _verify_once() -> None:
    """Single verification pass — re-deliver any unACKed query-status phases.

    Queries the DB for active queries created within the lookback window,
    then re-publishes any phases that have not been ACKed by the client.
    """
    settings = get_settings()
    lookback = timedelta(seconds=settings.STATUS_VERIFIER_LOOKBACK_SECS)
    cutoff = datetime.now(timezone.utc) - lookback

    factory = get_session_factory()
    try:
        async with factory() as session:
            rows = await session.scalars(
                select(UserQuery)
                .where(
                    and_(
                        UserQuery.status.in_(list(_ACTIVE_STATUSES)),
                        UserQuery.created_at >= cutoff,
                    )
                )
                .limit(200)
            )
            active_queries = list(rows.all())
    except Exception as exc:  # noqa: BLE001
        logger.warning("[status_verifier] DB query failed: %s", exc)
        return

    if not active_queries:
        return

    for uq in active_queries:
        thread_id: str = uq.thread_id
        unacked = await get_unacked_phases(thread_id)
        if not unacked:
            continue

        stream_id: str | None = await get_stream_id_for_thread(thread_id)
        for entry in unacked:
            phase: str = entry["phase"]
            retry_count: int = entry["retry_count"]
            if stream_id:
                logger.info(
                    "[status_verifier] re-publishing phase=%s retry=%d stream_id=%s",
                    phase,
                    retry_count,
                    stream_id,
                )
            else:
                logger.info(
                    "[status_verifier] re-publishing phase=%s retry=%d thread_id=%s",
                    phase,
                    retry_count,
                    thread_id,
                )
            try:
                await publish_thread_lifecycle(
                    thread_id,
                    {
                        "event": "query_status",
                        "phase": phase,
                        "thread_id": thread_id,
                        "is_double_check": True,
                    },
                )
                await increment_phase_retry(thread_id, phase)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[status_verifier] re-publish failed phase=%s thread_id=%s: %s",
                    phase,
                    thread_id,
                    exc,
                )


async def run_status_verifier() -> None:
    """Background loop that periodically re-delivers unACKed query-status phases.

    Starts an infinite ``asyncio`` loop; sleeps for
    :attr:`~backend.config.Settings.STATUS_VERIFIER_INTERVAL_SECS` between
    each verification pass.  Designed to run as an ``asyncio.Task`` from the
    assistant FastAPI lifespan.

    The loop runs to cancellation (``asyncio.CancelledError``), which is
    raised by :meth:`asyncio.Task.cancel` during app shutdown.
    """
    settings = get_settings()
    interval = settings.STATUS_VERIFIER_INTERVAL_SECS
    logger.info("[status_verifier] started interval=%ds lookback=%ds", interval, settings.STATUS_VERIFIER_LOOKBACK_SECS)
    try:
        while True:
            await asyncio.sleep(interval)
            try:
                await _verify_once()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[status_verifier] pass failed: %s", exc)
    except asyncio.CancelledError:
        logger.info("[status_verifier] stopped")


__all__ = ["run_status_verifier"]
