"""Streaming lifecycle — done-ACK handling.

When the client receives the ``done`` SSE event and completes its drain-phase
checks (all tasks in terminal state, all tokens received), it sends a
``POST /stream/{thread_id}/done-ack`` HTTP request.  The backend handles this
by calling :func:`ack_done` which removes the pending-notify entry for the
``done`` event so the drain cycle does not re-emit it.

This module is a thin domain facade over
:func:`~backend.db.redis.streams.publisher.ack_pending_notify` with done-ACK
semantics made explicit.
"""

from __future__ import annotations

import logging

from backend.db.redis.streams.publisher import ack_pending_notify

logger = logging.getLogger(__name__)


async def ack_done(thread_id: str) -> None:
    """Record that the client has acknowledged the ``done`` lifecycle event.

    Removes the ``done:0`` entry from the pending-notify Redis hash so the
    drain cycle does not re-emit the ``done`` event after the client has
    already processed it.

    This is called by ``POST /stream/{thread_id}/done-ack`` immediately after
    the client confirms it has entered the ``done`` phase.

    Args:
        thread_id: LangGraph thread UUID of the session being acknowledged.
    """
    await ack_pending_notify(thread_id, "done", None)
    logger.debug("[done_ack] acked thread_id=%s", thread_id)


__all__ = ["ack_done"]
