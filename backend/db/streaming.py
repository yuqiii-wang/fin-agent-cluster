"""PostgreSQL LISTEN/NOTIFY helpers for streaming graph task events.

Uses a dedicated asyncpg connection (outside SQLAlchemy) so notifications
are delivered in real-time without polling.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any, Callable

import asyncpg

from backend.config import get_settings

logger = logging.getLogger(__name__)


def _channel(thread_id: str) -> str:
    """Return a valid PostgreSQL channel name derived from the thread UUID.

    Args:
        thread_id: LangGraph UUID thread identifier.

    Returns:
        Channel name safe for ``LISTEN`` / ``pg_notify``, e.g. ``t_<uuid_no_hyphens>``.
    """
    return "t_" + thread_id.replace("-", "_")


async def notify(thread_id: str, payload: dict) -> None:
    """Send a ``pg_notify`` carrying *payload* on the thread's channel.

    Opens a short-lived asyncpg connection and closes it immediately after
    sending to avoid holding idle connections.

    Args:
        thread_id: LangGraph thread ID that identifies the channel.
        payload:   Dict to JSON-encode as the notification payload.
    """

    def _default(obj: Any) -> str:
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    settings = get_settings()
    try:
        conn: asyncpg.Connection = await asyncpg.connect(
            settings.DATABASE_URL,
            timeout=settings.DB_CONNECT_TIMEOUT_SECONDS,
        )
        channel = _channel(thread_id)
        await conn.execute("SELECT pg_notify($1, $2)", channel, json.dumps(payload, default=_default))
        await conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[streaming.notify] failed thread_id=%s: %s", thread_id, exc)


@asynccontextmanager
async def listen(
    thread_id: str,
) -> AsyncGenerator[asyncio.Queue[str], None]:
    """Async context manager that subscribes to the thread's notification channel.

    Yields a :class:`asyncio.Queue` that receives raw JSON strings whenever
    ``pg_notify`` fires on the channel.  The underlying asyncpg connection
    and listener are cleaned up on exit.

    Args:
        thread_id: LangGraph thread ID to subscribe to.

    Yields:
        Queue of raw JSON notification payloads.
    """
    settings = get_settings()
    conn: asyncpg.Connection = await asyncpg.connect(
        settings.DATABASE_URL,
        timeout=settings.DB_CONNECT_TIMEOUT_SECONDS,
    )
    channel = _channel(thread_id)
    queue: asyncio.Queue[str] = asyncio.Queue()

    def _on_notify(
        connection: asyncpg.Connection,
        pid: int,
        ch: str,
        payload: str,
    ) -> None:
        """Listener callback — puts the raw payload onto the queue."""
        queue.put_nowait(payload)

    await conn.add_listener(channel, _on_notify)
    await conn.execute(f"LISTEN {channel}")
    logger.debug("[streaming.listen] subscribed channel=%s", channel)

    try:
        yield queue
    finally:
        try:
            await conn.remove_listener(channel, _on_notify)
            await conn.execute(f"UNLISTEN {channel}")
        except Exception:  # noqa: BLE001
            pass
        await conn.close()
        logger.debug("[streaming.listen] unsubscribed channel=%s", channel)
