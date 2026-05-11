"""centrifugo.rpc_proxy — Centrifugo publish-proxy ack handler.

Receives RPC calls forwarded by Centrifugo's RPC proxy when a frontend
client calls ``centrifuge.rpc("thread_ack", data)``.  Dispatches to the
appropriate scoped ack handler, then publishes an ``ack_confirmed`` event
back via Centrifugo so the frontend can confirm round-trip delivery.

Scope hierarchy
---------------
  ``thread`` — thread-level events (done, query_status, …).
  ``node``   — node execution events (node_status, node_input, …).
  ``task``   — task lifecycle events (started / completed / failed / cancelled).
  ``stream`` — token-batch delivery tracking (emits ``stream_complete`` when all batches ACKed).

For ``thread``, ``node`` and ``task`` scopes the payload must include an
``ack_key`` string that matches the ``dedup_key`` used in the corresponding
:func:`~backend.centrifugo_mq.sse_notification.thread.notify` call.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.centrifugo_mq.client import publish_thread_event
from backend.db.redis.session.notify_ack_store import signal_notify_ack

logger = logging.getLogger(__name__)


async def handle_ack_rpc(thread_id: str, scope: str, data: dict[str, Any]) -> None:
    """Dispatch an inbound ack RPC to the correct scoped handler and publish confirmation.

    Called by the centrifugo RPC proxy endpoint after validating the proxy key.
    Errors inside scope handlers are caught and logged so a single bad payload
    does not prevent the confirmation event being returned.

    Args:
        thread_id: LangGraph thread UUID extracted from the Centrifugo channel.
        scope:     Ack scope string: ``"thread"``, ``"node"``, ``"task"``, or ``"stream"``.
        data:      Full RPC payload dict from the frontend (excluding ``scope``).
    """
    try:
        if scope in ("thread", "node", "task"):
            await _ack_notify(thread_id, scope, data)
        elif scope == "stream":
            await _ack_stream(thread_id, data)
        else:
            logger.warning("[rpc_proxy] unknown ack scope=%s thread_id=%s", scope, thread_id)
            return
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[rpc_proxy] ack handler error scope=%s thread_id=%s: %s",
            scope,
            thread_id,
            exc,
        )

    # Publish ack_confirmed back so the frontend can confirm round-trip delivery.
    await _publish_ack_confirmed(thread_id, scope, data)


# ---------------------------------------------------------------------------
# Scope handlers
# ---------------------------------------------------------------------------


async def _ack_notify(thread_id: str, scope: str, data: dict[str, Any]) -> None:
    """Signal ACK for a thread-, node- or task-scope SSE notification.

    The payload must include ``ack_key`` — the same key used in the
    corresponding :func:`~backend.centrifugo_mq.sse_notification.thread.notify`
    call.  The BLPOP waiter in the publisher is unblocked immediately.

    Args:
        thread_id: LangGraph thread UUID.
        scope:     ``"thread"``, ``"node"``, or ``"task"``.
        data:      RPC payload; must contain ``ack_key`` (str).
    """
    ack_key: str = data.get("ack_key", "")
    if not ack_key:
        logger.warning(
            "[rpc_proxy] missing ack_key scope=%s thread_id=%s", scope, thread_id
        )
        return
    logger.debug(
        "[rpc_proxy] ack scope=%s ack_key=%s thread_id=%s", scope, ack_key, thread_id
    )
    await signal_notify_ack(thread_id, ack_key)


async def _ack_stream(thread_id: str, data: dict[str, Any]) -> None:
    """Handle a stream-scope ACK, including token_batch delivery confirmation.

    For ``event_type="token_batch_ack"``: increments the per-stream ACK counter
    in Redis and emits ``stream_complete`` when all batches have been confirmed.

    Args:
        thread_id: LangGraph thread UUID.
        data:      RPC payload; expected to contain ``stream_id`` (str),
                   ``event_type`` (str), and optionally ``seq`` (int).
    """
    stream_id: str = data.get("stream_id", "")
    event_type: str = data.get("event_type", "")
    logger.debug(
        "[rpc_proxy] stream ack event_type=%s stream_id=%s thread_id=%s",
        event_type,
        stream_id,
        thread_id,
    )

    if event_type != "token_batch_ack" or not stream_id:
        return

    from backend.db.redis.session.stream_batch_ack_store import (  # noqa: PLC0415
        record_batch_ack,
        try_claim_emit_slot,
    )
    from backend.sse_notifications.thread.node.task.stream import (  # noqa: PLC0415
        emit_stream_complete,
    )

    acked, meta = await record_batch_ack(stream_id, thread_id)
    if meta is None:
        # Celery has not yet stored the total — ACK arrived early; emit will
        # fire when the Celery worker stores meta and checks.
        return

    total_batches: int = meta["total_batches"]
    if acked < total_batches:
        return

    claimed = await try_claim_emit_slot(stream_id, meta["thread_id"])
    if not claimed:
        return

    await emit_stream_complete(
        thread_id=meta["thread_id"],
        stream_id=stream_id,
        node_id=meta["node_id"],
        task_id=meta["task_id"],
        total_tokens=meta["total_tokens"],
        tps=meta["tps"],
        total_batches=total_batches,
        ingest_ms=meta.get("ingest_ms", 0),
    )


# ---------------------------------------------------------------------------
# Confirmation publisher
# ---------------------------------------------------------------------------


async def _publish_ack_confirmed(
    thread_id: str, scope: str, data: dict[str, Any]
) -> None:
    """Publish an ``ack_confirmed`` event back to the frontend via Centrifugo.

    Args:
        thread_id: LangGraph thread UUID.
        scope:     Ack scope that was processed.
        data:      Original ack payload (forwarded so the frontend can correlate).
    """
    payload: dict[str, Any] = {"event": "ack_confirmed", "scope": scope, **data}
    await publish_thread_event(thread_id, payload)

