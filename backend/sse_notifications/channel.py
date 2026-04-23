"""SSE notification transport — PostgreSQL NOTIFY helpers.

This module owns the low-level ``pg_notify`` call and the shared PG channel
convention.  All lifecycle events are published to the single shared channel
``SHARED_LIFECYCLE_CHANNEL`` (``sse_lifecycle``) rather than per-thread
channels.  The fanout task in :mod:`backend.db.redis.lifecycle_fanout` listens
on this channel, extracts ``thread_id`` from each payload, and PUBLISH-es to
the appropriate Redis Pub/Sub channel for delivery to SSE subscribers.

Design rule:
  ``pg_notify`` fires **only after** the related DB commit has been issued,
  so the notification payload always reflects durable, authoritative data.
  High-frequency token events never go through this path — they travel via
  Redis Streams (see :mod:`backend.db.redis`).
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from backend.db.postgres.connection import raw_conn

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# PostgreSQL NOTIFY payload hard limit (8 000 bytes).
_PG_NOTIFY_MAX_BYTES = 7_900

#: Single shared PostgreSQL NOTIFY/LISTEN channel for all lifecycle events.
#: The fanout task subscribes here and routes events to per-thread Redis
#: Pub/Sub channels based on ``thread_id`` in the payload.
SHARED_LIFECYCLE_CHANNEL: str = "sse_lifecycle"


def _json_default(obj: Any) -> str:
    """JSON serializer for types not handled by the stdlib encoder.

    Args:
        obj: Object that failed default JSON serialization.

    Returns:
        ISO-format string for date / datetime objects.

    Raises:
        TypeError: For all other unsupported types.
    """
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


async def pg_notify(thread_id: str, payload: dict[str, Any]) -> None:
    """Fire a PostgreSQL NOTIFY on the shared lifecycle channel.

    Uses a raw connection with ``autocommit=True`` so the notification is
    delivered immediately without a surrounding transaction.  Must be called
    **after** the relevant ``session.commit()`` so the DB data is durable.

    Injects ``thread_id`` into the payload (if not already present) so the
    fanout task can route the event to the correct per-thread Redis channel.

    Payloads exceeding :data:`_PG_NOTIFY_MAX_BYTES` have their ``"output"``
    field replaced with ``{"_truncated": True}`` to stay within the limit.

    Args:
        thread_id: LangGraph thread UUID.
        payload:   Event dict to JSON-encode.  Must include an ``"event"`` key.
    """
    if "thread_id" not in payload:
        payload = {**payload, "thread_id": thread_id}
    raw = json.dumps(payload, default=_json_default)

    if len(raw.encode()) > _PG_NOTIFY_MAX_BYTES:
        truncated = dict(payload)
        if "output" in truncated:
            truncated["output"] = {"_truncated": True}
        raw = json.dumps(truncated, default=_json_default)
        logger.warning(
            "[sse_notifications.channel] payload_truncated event=%s thread_id=%s",
            payload.get("event", "?"),
            thread_id,
        )

    try:
        async with raw_conn() as conn:
            await conn.execute("SELECT pg_notify(%s, %s)", [SHARED_LIFECYCLE_CHANNEL, raw])
        logger.debug(
            "[sse_notifications.channel] sent event=%s channel=%s",
            payload.get("event", "?"),
            SHARED_LIFECYCLE_CHANNEL,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[sse_notifications.channel] failed event=%s thread_id=%s: %s",
            payload.get("event", "?"),
            thread_id,
            exc,
        )


async def pg_notify_in_session(
    session: "AsyncSession",
    thread_id: str,
    payload: dict[str, Any],
) -> None:
    """Queue a PostgreSQL NOTIFY **inside** an open transaction.

    Unlike :func:`pg_notify`, this function executes ``SELECT pg_notify(...)``
    on the existing SQLAlchemy session connection.  PostgreSQL defers delivery
    of any ``NOTIFY`` issued within a transaction until ``COMMIT``, guaranteeing
    that DB writes made in the same transaction (e.g. ``streamings`` rows) are
    already visible to every subscriber that receives the notification.

    Injects ``thread_id`` into the payload (if not already present) so the
    fanout task can route the event to the correct per-thread Redis channel.

    Must be called **before** ``session.commit()`` — the notification is only
    delivered when the transaction commits.

    Args:
        session:   Open SQLAlchemy async session with an active transaction.
        thread_id: LangGraph thread UUID.
        payload:   Event dict to JSON-encode.  Must include an ``"event"`` key.
    """
    from sqlalchemy import text  # local import keeps top-level deps minimal

    if "thread_id" not in payload:
        payload = {**payload, "thread_id": thread_id}
    raw = json.dumps(payload, default=_json_default)

    if len(raw.encode()) > _PG_NOTIFY_MAX_BYTES:
        truncated = dict(payload)
        if "output" in truncated:
            truncated["output"] = {"_truncated": True}
        raw = json.dumps(truncated, default=_json_default)
        logger.warning(
            "[sse_notifications.channel] payload_truncated event=%s thread_id=%s",
            payload.get("event", "?"),
            thread_id,
        )

    await session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": SHARED_LIFECYCLE_CHANNEL, "payload": raw},
    )
    logger.debug(
        "[sse_notifications.channel] queued_in_txn event=%s channel=%s",
        payload.get("event", "?"),
        SHARED_LIFECYCLE_CHANNEL,
    )


__all__ = [
    "SHARED_LIFECYCLE_CHANNEL",
    "pg_notify",
    "pg_notify_in_session",
]
