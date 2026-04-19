"""PostgreSQL LISTEN subscriber for task lifecycle events.

Provides the ``pg_listen`` async context manager that opens a dedicated
psycopg3 async connection per SSE subscriber, issues ``LISTEN`` on the
thread's task-events channel, and pumps incoming notifications onto an
``asyncio.Queue`` for consumption by the SSE generator.

Only **task lifecycle** events arrive here (started, completed, failed,
cancelled, done).  Token events travel through Redis Streams.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from backend.config import get_settings
from backend.sse_notifications.channel import notify_channel

logger = logging.getLogger(__name__)

# How long (seconds) to wait for a notification before looping.
# Controls how quickly the pump task responds to cancellation.
_NOTIFY_TIMEOUT = 5.0


@asynccontextmanager
async def pg_listen(
    thread_id: str,
) -> AsyncGenerator[asyncio.Queue[str], None]:
    """Async context manager that listens for task lifecycle events via pg_notify.

    Opens a dedicated psycopg3 async connection in autocommit mode, issues
    ``LISTEN`` on the thread's channel, and spawns a background task that
    pumps incoming notification payloads onto an ``asyncio.Queue``.

    Args:
        thread_id: LangGraph thread ID to listen for.

    Yields:
        Queue of raw JSON notification payloads (strings).
    """
    settings = get_settings()
    channel = notify_channel(thread_id)
    queue: asyncio.Queue[str] = asyncio.Queue()

    conn: AsyncConnection = await AsyncConnection.connect(
        settings.DATABASE_PG_URL,
        connect_timeout=settings.DB_CONNECT_TIMEOUT_SECONDS,
        autocommit=True,
        row_factory=dict_row,
    )
    await conn.execute(f'LISTEN "{channel}"')
    logger.debug("[listener.pg_listen] listening channel=%s", channel)

    async def _pump() -> None:
        """Background task — relay pg_notify payloads onto the queue."""
        notification_count = 0
        try:
            async for notification in conn.notifies(timeout=_NOTIFY_TIMEOUT):
                if notification.payload:
                    queue.put_nowait(notification.payload)
                    notification_count += 1
                    if notification_count == 1:
                        try:
                            parsed = json.loads(notification.payload)
                            logger.debug(
                                "[listener._pump] first_notification event=%s channel=%s",
                                parsed.get("event", "?"),
                                channel,
                            )
                        except Exception:  # noqa: BLE001
                            logger.debug(
                                "[listener._pump] first_notification channel=%s",
                                channel,
                            )
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("[listener._pump] error channel=%s: %s", channel, exc)

    pump_task: asyncio.Task[None] = asyncio.create_task(_pump())

    try:
        yield queue
    finally:
        pump_task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(pump_task), timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
        try:
            await conn.execute(f'UNLISTEN "{channel}"')
        except Exception:  # noqa: BLE001
            pass
        try:
            await conn.close()
        except Exception:  # noqa: BLE001
            pass
        logger.debug("[listener.pg_listen] unlistened channel=%s", channel)
