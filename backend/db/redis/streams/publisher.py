"""Redis Streams token publisher.

Provides :func:`stream_token` which publishes high-frequency LLM token events
to ``fin:llm:tokens`` (shard-routed by thread_id).  Centrifugo's native Redis
Stream consumer picks up entries and delivers them to WebSocket clients,
keeping FastAPI completely out of the token delivery path.

Each stream entry uses two fields as required by Centrifugo v6's async consumer:
- ``method``: ``"publish"`` — tells the consumer which API command to execute.
- ``payload``: JSON-serialised publish request ``{"channel": "thread:{thread_id}",
  "data": <event>}`` — the body of the publish command.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.streaming.streams import STREAM_TOKEN, xadd_sharded

logger = logging.getLogger(__name__)

# Per-thread counter so we only log the first XADD to fin:llm:tokens per thread.
# This is a module-level dict keyed by thread_id — only used for debug auditing.
_xadd_logged: set[str] = set()


def stream_key(thread_id: str) -> str:
    """Return the legacy Redis Stream key name for *thread_id*.

    No longer written to — kept so that :func:`cleanup_thread_session` can
    issue a safe no-op DEL without changes.

    Args:
        thread_id: LangGraph UUID thread identifier.

    Returns:
        Stream key string, e.g. ``tokens:<uuid>``.
    """
    return f"tokens:{thread_id}"


async def stream_token(thread_id: str, payload: dict[str, Any]) -> None:
    """XADD a token event to ``fin:llm:tokens`` on the correct Redis shard.

    Centrifugo's native Redis consumer reads this entry and delivers it to
    all WebSocket subscribers on channel ``thread:{thread_id}``.

    The stream entry uses the two-field format required by Centrifugo v6:
    ``method=publish`` and ``payload=<publish request JSON>``.

    Args:
        thread_id: LangGraph thread ID (determines shard + channel name).
        payload:   Token event dict — must include ``"event": "token"``.
    """
    payload_value = json.dumps({"channel": f"thread:{thread_id}", "data": payload})
    entry = {"method": "publish", "payload": payload_value}
    if thread_id not in _xadd_logged:
        _xadd_logged.add(thread_id)
        logger.info(
            "[stream_token] first xadd thread_id=%s stream=%s entry_keys=%s",
            thread_id, STREAM_TOKEN, list(entry.keys()),
        )
    await xadd_sharded(thread_id, STREAM_TOKEN, entry)


__all__ = [
    "stream_key",
    "stream_token",
]

