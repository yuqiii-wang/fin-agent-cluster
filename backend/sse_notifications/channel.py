"""sse_notifications.channel -- lifecycle event publication via Centrifugo.

Every lifecycle event (started, completed, failed, cancelled, done, query_*,
perf_*, node_*) is published to the per-thread Centrifugo channel
``thread:{thread_id}`` via the Centrifugo HTTP API.

Design rule:
  :func:`publish_lifecycle` must be called **after** the related DB commit so
  the notification payload always reflects durable, authoritative data.
  High-frequency token events travel via the same Centrifugo channel
  (see :func:`~backend.db.redis.streams.publisher.stream_token`).
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

from backend.centrifugo.client import publish_to_channel

logger = logging.getLogger(__name__)


def _json_default(obj: Any) -> str:
    """JSON serializer for types not handled by the stdlib encoder."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


async def publish_lifecycle(thread_id: str, payload: dict[str, Any]) -> None:
    """Publish a lifecycle event to the Centrifugo ``thread:{thread_id}`` channel.

    Injects ``thread_id`` into the payload (if not already present) and
    publishes to the Centrifugo node that owns this thread's shard.

    Must be called **after** the relevant ``session.commit()`` so the DB row
    is already durable when the subscriber reads it.

    Args:
        thread_id: LangGraph thread UUID.
        payload:   Event dict.  Must include an ``"event"`` key.
    """
    if "thread_id" not in payload:
        payload = {**payload, "thread_id": thread_id}

    # Coerce non-serialisable values (datetime -> ISO string).
    try:
        json.dumps(payload, default=_json_default)
    except TypeError:
        payload = json.loads(json.dumps(payload, default=_json_default))

    await publish_to_channel(thread_id, payload)
    logger.debug(
        "[sse_notifications.channel] published event=%s thread_id=%s",
        payload.get("event", "?"),
        thread_id,
    )


__all__ = [
    "publish_lifecycle",
]
