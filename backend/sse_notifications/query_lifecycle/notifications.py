"""Query lifecycle SSE notification emitters.

Both functions use :func:`backend.sse_notifications.channel.pg_notify` for
live delivery.  ``emit_query_received`` additionally calls
:func:`backend.db.redis.publisher.push_pending_notify` so the SSE generator's
drain cycle retries delivery if the client was not yet subscribed when the
notification fired.

``emit_query_status`` emits phase-transition events used by both regular and
perf-test queries.  It lives here (not in the perf_test sub-package) because
phase transitions are universal to every query type.
"""

from __future__ import annotations

import json
import logging

from backend.db.redis.publisher import push_pending_notify
from backend.sse_notifications.channel import pg_notify

logger = logging.getLogger(__name__)


async def emit_query_received(thread_id: str) -> None:
    """Emit ``query_received`` via pg_notify and push to the pending-notify store.

    The pending-notify store ensures the event is retried by the SSE generator's
    drain cycle (every ~1–300 s with exponential back-off) until the client
    confirms receipt via the ACK endpoint.

    Args:
        thread_id: LangGraph thread UUID.
    """
    payload = {"event": "query_received", "thread_id": thread_id}
    raw = json.dumps(payload)
    await push_pending_notify(thread_id, "query_received", None, raw)
    await pg_notify(thread_id, payload)
    logger.info("[query_lifecycle] query_received emitted thread_id=%s", thread_id)


async def emit_query_ack_confirmed(thread_id: str) -> None:
    """Emit ``query_ack_confirmed`` via pg_notify.

    No pending-notify store entry is created because this event is the
    terminal confirmation — the client stops retrying ACKs on receipt, and
    subsequent ``started`` task events signal graph progress.

    Args:
        thread_id: LangGraph thread UUID.
    """
    await pg_notify(
        thread_id,
        {"event": "query_ack_confirmed", "thread_id": thread_id},
    )
    logger.info("[query_lifecycle] query_ack_confirmed emitted thread_id=%s", thread_id)


async def emit_query_status(thread_id: str, phase: str) -> None:
    """Emit a ``query_status`` SSE event signalling a backend phase transition.

    Fires via pg_notify so the frontend can update status in real time.  The
    phase is stored in Redis by the caller so late-connecting SSE clients
    recover the current phase via :func:`~backend.api.stream._replay_existing`.

    This function is the single canonical emitter for ``query_status`` events
    across all query types (regular and perf-test).

    Phase progression for regular queries:
        ``received`` → ``preparing``

    Phase progression for perf-test queries:
        ``received`` → ``preparing`` → ``ingesting`` → ``sending``

    Args:
        thread_id: LangGraph thread UUID.
        phase:     One of ``"received"``, ``"preparing"``, ``"ingesting"``,
                   ``"sending"``.
    """
    await pg_notify(thread_id, {"event": "query_status", "phase": phase})
    logger.info("[query_lifecycle] query_status emitted phase=%s thread_id=%s", phase, thread_id)


__all__ = ["emit_query_received", "emit_query_ack_confirmed", "emit_query_status"]
