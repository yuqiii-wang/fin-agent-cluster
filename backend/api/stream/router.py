"""FastAPI router — stream utility endpoints.

Real-time event streaming is delivered via Centrifugo WebSocket
(see ``backend.api.centrifugo``).  This router exposes:

  * ``POST /stream/{thread_id}/done-ack``    -- client acknowledgement of the ``done`` event.
  * ``POST /stream/{thread_id}/status-ack``  -- client acknowledgement of a ``query_status`` phase.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from backend.db.redis.session.query_status_ack_store import ack_query_status_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stream", tags=["stream"])


class _DoneAckRequest(BaseModel):
    """Body for ``POST /stream/{thread_id}/done-ack``."""

    status: str


class _DoneAckResponse(BaseModel):
    """Response for ``POST /stream/{thread_id}/done-ack``."""

    acknowledged: bool
    thread_id: str


class _StatusAckRequest(BaseModel):
    """Body for ``POST /stream/{thread_id}/status-ack``."""

    phase: str
    is_double_check: bool = False


class _StatusAckResponse(BaseModel):
    """Response for ``POST /stream/{thread_id}/status-ack``."""

    acknowledged: bool
    thread_id: str
    phase: str


@router.post("/{thread_id}/done-ack", response_model=_DoneAckResponse, status_code=200)
async def done_ack(thread_id: str, body: _DoneAckRequest) -> _DoneAckResponse:
    """Receive the client's done-acknowledgement for *thread_id*.

    Called by the frontend after the ``DoneConditionGuard`` has resolved.
    No-op on the backend now that the pending-notify store is removed;
    kept for forward-compatibility and logging.

    Args:
        thread_id: LangGraph thread UUID.
        body:      ``{"status": "completed" | "failed" | "timeout" | ...}``.

    Returns:
        ``{"acknowledged": true, "thread_id": "<uuid>"}``
    """
    logger.info("[stream] done_ack status=%s thread_id=%s", body.status, thread_id)
    return _DoneAckResponse(acknowledged=True, thread_id=thread_id)


@router.post("/{thread_id}/status-ack", response_model=_StatusAckResponse, status_code=200)
async def status_ack(thread_id: str, body: _StatusAckRequest) -> _StatusAckResponse:
    """Receive the client's acknowledgement of a ``query_status`` lifecycle phase.

    Called by the frontend when it successfully processes a ``query_status``
    Centrifugo event.  Marks the phase as ACKed in the Redis query-status ACK
    store so the assistant verifier skips re-delivery for this phase.

    Routes to ``assistant-upstream`` via Kong (``POST /api/v1/stream/*``).

    Args:
        thread_id: LangGraph thread UUID.
        body:      ``{"phase": "received" | "preparing" | "ingesting" | "digesting",
                   "is_double_check": false | true}``.
                   ``is_double_check=True`` is set by the frontend when this ACK is
                   triggered by an assistant-verifier re-delivery; Kong uses the
                   ``X-Double-Check: true`` request header to pin these to assistant.

    Returns:
        ``{"acknowledged": true, "thread_id": "<uuid>", "phase": "<phase>"}``
    """
    logger.debug(
        "[stream] status_ack phase=%s is_double_check=%s thread_id=%s",
        body.phase,
        body.is_double_check,
        thread_id,
    )
    await ack_query_status_event(thread_id, body.phase)
    return _StatusAckResponse(acknowledged=True, thread_id=thread_id, phase=body.phase)
