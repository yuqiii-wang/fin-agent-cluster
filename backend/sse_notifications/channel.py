"""SSE notification transport — direct Redis Pub/Sub publish for lifecycle events.

Every lifecycle event (started, completed, failed, cancelled, done, query_*,
perf_*, node_*) is published **directly** to the per-thread Redis Pub/Sub
channel ``lifecycle:<thread_id>`` via :func:`publish_lifecycle`.

Design rule:
  :func:`publish_lifecycle` must be called **after** the related DB commit so
  the notification payload always reflects durable, authoritative data.
  High-frequency token events travel via Redis Streams (see
  :mod:`backend.db.redis`), not through this module.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

from backend.db.redis.lifecycle.subscriber import lifecycle_pub_channel
from backend.db.redis.router import get_redis_router
from backend.sse_notifications.errors import SSE_PUBLISH_FAILED

logger = logging.getLogger(__name__)


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


async def publish_lifecycle(thread_id: str, payload: dict[str, Any]) -> None:
    """Publish a lifecycle event directly to the Redis Pub/Sub channel.

    Injects ``thread_id`` into the payload (if not already present) and
    PUBLISHes to ``lifecycle:<thread_id>`` on the shard that owns this
    thread so SSE subscribers receive the event immediately.

    Must be called **after** the relevant ``session.commit()`` so the DB row
    is already durable when the subscriber reads it.

    Args:
        thread_id: LangGraph thread UUID.
        payload:   Event dict to JSON-encode.  Must include an ``"event"`` key.
    """
    if "thread_id" not in payload:
        payload = {**payload, "thread_id": thread_id}
    raw = json.dumps(payload, default=_json_default)
    channel = lifecycle_pub_channel(thread_id)

    try:
        router = get_redis_router()
        client = router.get_client_for_thread(thread_id)
        await client.publish(channel, raw)
        logger.debug(
            "[sse_notifications.channel] published event=%s channel=%s",
            payload.get("event", "?"),
            channel,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[%s] failed event=%s thread_id=%s: %s",
            SSE_PUBLISH_FAILED,
            payload.get("event", "?"),
            thread_id,
            exc,
        )


__all__ = [
    "publish_lifecycle",
]
