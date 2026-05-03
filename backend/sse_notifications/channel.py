"""sse_notifications.channel -- scope-based lifecycle event publication via Centrifugo.

Every lifecycle event is published to the per-thread Centrifugo channel
``thread:{thread_id}`` via the Centrifugo HTTP API.

Scope hierarchy
---------------
Events are classified into four scopes that reflect where their authoritative
timestamps come from:

* **Thread** — ``done``, ``query_received``, ``query_ack_confirmed``, ``query_status``
  Timestamps from ``fin_agents.user_queries``.

* **Node** — ``node_input``, ``node_output``, ``node_status``
  Timestamps derived from ``fin_agents.node_executions`` (``started_at`` + ``elapsed_ms``).

* **Task** — ``started``, ``completed``, ``failed``, ``cancelled``
  Timestamps from ``fin_agents.tasks`` (``created_at`` / ``updated_at``).

* **Stream** — ``ingest_complete``, ``stream_stopped``, ``stream_complete``
  Ephemeral; not persisted in PG DB.  Wall-clock values from the streaming worker.

Design rule
-----------
  Each publish function must be called **after** the related DB commit so the
  notification payload always reflects durable, authoritative data.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

from backend.centrifugo.client import (
    publish_node_event as _pub_node,
    publish_stream_event as _pub_stream,
    publish_task_event as _pub_task,
    publish_thread_event as _pub_thread,
)

logger = logging.getLogger(__name__)


def _json_default(obj: Any) -> str:
    """JSON serializer for types not handled by the stdlib encoder."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _prepare_payload(thread_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Inject ``thread_id`` and coerce non-serialisable values (datetime → ISO string).

    Args:
        thread_id: LangGraph thread UUID.
        payload:   Raw event dict.

    Returns:
        Prepared payload ready for JSON serialisation.
    """
    if "thread_id" not in payload:
        payload = {**payload, "thread_id": thread_id}
    try:
        json.dumps(payload, default=_json_default)
    except TypeError:
        payload = json.loads(json.dumps(payload, default=_json_default))
    return payload


async def publish_thread_lifecycle(thread_id: str, payload: dict[str, Any]) -> None:
    """Publish a thread-level lifecycle event (done, query_status, query_received, etc.).

    Authoritative timestamps come from ``fin_agents.user_queries``.
    Must be called after the relevant ``session.commit()``.

    Args:
        thread_id: LangGraph thread UUID.
        payload:   Event dict.  Must include an ``"event"`` key.
    """
    payload = _prepare_payload(thread_id, payload)
    await _pub_thread(thread_id, payload)
    logger.debug(
        "[channel] thread event=%s thread_id=%s",
        payload.get("event", "?"),
        thread_id,
    )


async def publish_node_lifecycle(thread_id: str, payload: dict[str, Any]) -> None:
    """Publish a node-level lifecycle event (node_input, node_output, node_status).

    Timestamps in the payload must be derived from ``fin_agents.node_executions``
    (``started_at`` + ``elapsed_ms``), not from wall-clock time at emit.
    Must be called after the relevant ``session.commit()``.

    Args:
        thread_id: LangGraph thread UUID.
        payload:   Event dict.  Must include an ``"event"`` key.
    """
    payload = _prepare_payload(thread_id, payload)
    await _pub_node(thread_id, payload)
    logger.debug(
        "[channel] node event=%s thread_id=%s",
        payload.get("event", "?"),
        thread_id,
    )


async def publish_task_lifecycle(thread_id: str, payload: dict[str, Any]) -> None:
    """Publish a task-level lifecycle event (started, completed, failed, cancelled).

    Timestamps in the payload must come from ``fin_agents.tasks``
    (``created_at`` / ``updated_at``), not from wall-clock time at emit.
    Must be called after the relevant ``session.commit()``.

    Args:
        thread_id: LangGraph thread UUID.
        payload:   Event dict.  Must include an ``"event"`` key.
    """
    payload = _prepare_payload(thread_id, payload)
    await _pub_task(thread_id, payload)
    logger.debug(
        "[channel] task event=%s thread_id=%s",
        payload.get("event", "?"),
        thread_id,
    )


async def publish_stream_lifecycle(thread_id: str, payload: dict[str, Any]) -> None:
    """Publish a stream-level event (ingest_complete, stream_stopped, stream_complete).

    Stream events are ephemeral — not persisted in PG DB.
    Timestamps are wall-clock values from the streaming worker.

    Args:
        thread_id: LangGraph thread UUID.
        payload:   Event dict.  Must include an ``"event"`` key.
    """
    payload = _prepare_payload(thread_id, payload)
    await _pub_stream(thread_id, payload)
    logger.debug(
        "[channel] stream event=%s thread_id=%s",
        payload.get("event", "?"),
        thread_id,
    )


__all__ = [
    "publish_thread_lifecycle",
    "publish_node_lifecycle",
    "publish_task_lifecycle",
    "publish_stream_lifecycle",
]

