"""SSE notification transport — PostgreSQL NOTIFY helpers.

This module owns the low-level ``pg_notify`` call and the channel-naming
convention shared by notifier (sender) and listener (receiver).

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
from typing import Any

from backend.db.postgres.connection import raw_conn

logger = logging.getLogger(__name__)

# PostgreSQL NOTIFY payload hard limit (8 000 bytes).
_PG_NOTIFY_MAX_BYTES = 7_900

# Channel prefix.  Full channel = f"{_CHANNEL_PREFIX}{thread_id}".
_CHANNEL_PREFIX = "task_events:"


def notify_channel(thread_id: str) -> str:
    """Return the PostgreSQL NOTIFY/LISTEN channel name for *thread_id*.

    Channel names are limited to 63 characters in PostgreSQL.  A UUID-v4
    thread_id is 36 chars; the prefix is 12 chars → 48 chars total.

    Args:
        thread_id: LangGraph UUID thread identifier.

    Returns:
        Channel name, e.g. ``"task_events:<uuid>"``.
    """
    return f"{_CHANNEL_PREFIX}{thread_id}"


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
    """Fire a PostgreSQL NOTIFY on the thread's task-events channel.

    Uses a raw connection with ``autocommit=True`` so the notification is
    delivered immediately without a surrounding transaction.  Must be called
    **after** the relevant ``session.commit()`` so the DB data is durable.

    Payloads exceeding :data:`_PG_NOTIFY_MAX_BYTES` have their ``"output"``
    field replaced with ``{"_truncated": True}`` to stay within the limit.

    Args:
        thread_id: LangGraph thread UUID.
        payload:   Event dict to JSON-encode.  Must include an ``"event"`` key.
    """
    channel = notify_channel(thread_id)
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
            await conn.execute("SELECT pg_notify(%s, %s)", [channel, raw])
        logger.debug(
            "[sse_notifications.channel] sent event=%s channel=%s",
            payload.get("event", "?"),
            channel,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[sse_notifications.channel] failed event=%s thread_id=%s: %s",
            payload.get("event", "?"),
            thread_id,
            exc,
        )


__all__ = [
    "notify_channel",
    "pg_notify",
]
