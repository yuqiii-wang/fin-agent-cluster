"""Thread-level lifecycle SSE notifications.

Covers all events scoped to the top-level thread / query session:

* ``done``                — the entire LangGraph query finished.
* ``query_received``      — backend accepted the query; client must ACK to start execution.
* ``query_ack_confirmed`` — backend received the ACK; LangGraph execution is starting.
* ``query_status``        — phase-transition event for all query types.

All events use :func:`backend.sse_notifications.channel.publish_thread_lifecycle`
for live delivery via Centrifugo.

After each ``query_status`` event is published the phase is recorded in the
Redis query-status ACK store (``query_status_ack:{thread_id}``) as unACKed.
The assistant status-verifier background task re-publishes unACKed phases for
clients that miss them during connection setup.
"""

from __future__ import annotations

import logging

from backend.sse_notifications.channel import publish_thread_lifecycle
from backend.db.redis.session.query_status_ack_store import record_query_status_event

logger = logging.getLogger(__name__)


async def emit_done(
    thread_id: str,
    status: str,
    report: str = "",
    error_code: str | None = None,
) -> None:
    """Emit a terminal ``done`` SSE event for the thread.

    Args:
        thread_id:  LangGraph thread UUID.
        status:     Final session status emitted to the client.
        report:     Optional short excerpt of the final report (first 500 chars).
        error_code: Optional structured error code for ``"failed"`` status.
    """
    from backend.streaming.errors import STREAMING_ERRORS  # deferred

    _done_payload: dict = {
        "event": "done",
        "status": status,
        "data": report[:500] if report else "",
    }
    if error_code:
        _done_payload["error_code"] = error_code
        desc = STREAMING_ERRORS.get(error_code)
        if desc:
            _done_payload["error_description"] = desc
    logger.info("[thread] publish event=done status=%s thread_id=%s", status, thread_id)
    await publish_thread_lifecycle(thread_id, _done_payload)
    logger.info("[thread] done_emitted status=%s thread_id=%s", status, thread_id)


async def emit_query_received(thread_id: str) -> None:
    """Emit ``query_received`` via Centrifugo.

    Args:
        thread_id: LangGraph thread UUID.
    """
    payload = {"event": "query_received", "thread_id": thread_id}
    await publish_thread_lifecycle(thread_id, payload)
    logger.info("[thread] query_received emitted thread_id=%s", thread_id)


async def emit_query_ack_confirmed(thread_id: str) -> None:
    """Emit ``query_ack_confirmed`` via Centrifugo.

    Args:
        thread_id: LangGraph thread UUID.
    """
    await publish_thread_lifecycle(thread_id, {"event": "query_ack_confirmed", "thread_id": thread_id})
    logger.info("[thread] query_ack_confirmed emitted thread_id=%s", thread_id)


async def emit_query_status(
    thread_id: str,
    phase: str,
    *,
    stream_id: str | None = None,
) -> None:
    """Emit a ``query_status`` phase-transition event via Centrifugo.

    Also records the phase in the Redis query-status ACK store so the
    assistant verifier can re-deliver it if the client does not ACK within
    the verification interval.

    If *stream_id* is provided (concurrency / throughput modes) it is stored
    in the ACK hash so the status-verifier can log it instead of *thread_id*,
    making per-stream debugging easier.

    Args:
        thread_id: LangGraph thread UUID.
        phase:     Phase label, e.g. ``"received"``, ``"preparing"``, ``"ingesting"``,
                   ``"digesting"``.
        stream_id: Optional streaming session UUID.
    """
    from backend.db.redis.session.query_status_ack_store import (  # noqa: PLC0415
        store_stream_id_for_thread,
    )

    await publish_thread_lifecycle(thread_id, {"event": "query_status", "phase": phase, "thread_id": thread_id})
    await record_query_status_event(thread_id, phase)
    if stream_id is not None:
        await store_stream_id_for_thread(thread_id, stream_id)
    logger.debug("[thread] query_status phase=%s thread_id=%s", phase, thread_id)


__all__ = [
    "emit_done",
    "emit_query_received",
    "emit_query_ack_confirmed",
    "emit_query_status",
]
