"""Query lifecycle notification emitters.

Both functions use :func:`backend.sse_notifications.channel.publish_lifecycle`
for live delivery via Centrifugo.

``emit_query_status`` emits phase-transition events used by both regular and
perf-test queries.  It lives here (not in the perf_test sub-package) because
phase transitions are universal to every query type.

After each ``query_status`` event is published, the phase is recorded in the
Redis query-status ACK store (``query_status_ack:{thread_id}``) as unACKed.
The assistant status-verifier background task re-publishes unACKed phases for
clients that miss them during connection setup.
"""

from __future__ import annotations

import logging

from backend.sse_notifications.channel import publish_lifecycle
from backend.db.redis.session.query_status_ack_store import record_query_status_event

logger = logging.getLogger(__name__)


async def emit_query_received(thread_id: str) -> None:
    """Emit ``query_received`` via Centrifugo.

    Args:
        thread_id: LangGraph thread UUID.
    """
    payload = {"event": "query_received", "thread_id": thread_id}
    await publish_lifecycle(thread_id, payload)
    logger.info("[query_lifecycle] query_received emitted thread_id=%s", thread_id)


async def emit_query_ack_confirmed(thread_id: str) -> None:
    """Emit ``query_ack_confirmed`` via Centrifugo.

    Args:
        thread_id: LangGraph thread UUID.
    """
    await publish_lifecycle(thread_id, {"event": "query_ack_confirmed", "thread_id": thread_id})
    logger.info("[query_lifecycle] query_ack_confirmed emitted thread_id=%s", thread_id)


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

    await publish_lifecycle(thread_id, {"event": "query_status", "phase": phase, "thread_id": thread_id})
    await record_query_status_event(thread_id, phase)
    if stream_id is not None:
        await store_stream_id_for_thread(thread_id, stream_id)
    logger.debug("[query_lifecycle] query_status phase=%s thread_id=%s", phase, thread_id)
