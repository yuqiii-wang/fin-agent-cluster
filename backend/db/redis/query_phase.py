"""Ephemeral query-phase tracking in Redis.

Stores the current backend processing phase for a query so that
late-connecting SSE clients can recover the current state without relying on
pg_notify events that may have fired before the stream was open.

Key:    ``fin:query:phase:{thread_id}`` (string)
TTL:    600 s  (covers the longest perf-test run with a safety margin)
Values: ``"received"`` | ``"preparing"`` | ``"ingesting"`` | ``"sending"``
"""

from __future__ import annotations

import logging
from typing import Optional

from backend.db.redis.publisher import _get_publish_client

logger = logging.getLogger(__name__)

_PHASE_KEY_PREFIX: str = "fin:query:phase:"
_PHASE_TTL_SECS: int = 600


def _phase_key(thread_id: str) -> str:
    """Return the Redis key for the query phase of *thread_id*."""
    return f"{_PHASE_KEY_PREFIX}{thread_id}"


async def set_query_phase(thread_id: str, phase: str) -> None:
    """Store the current processing phase for *thread_id* in Redis.

    Uses SETEX so the key auto-expires after :data:`_PHASE_TTL_SECS` seconds
    even if the query is abandoned without explicit cleanup.

    Args:
        thread_id: LangGraph UUID thread identifier.
        phase:     One of ``"received"``, ``"preparing"``, ``"ingesting"``,
                   ``"sending"``.
    """
    client = await _get_publish_client()
    await client.setex(_phase_key(thread_id), _PHASE_TTL_SECS, phase)
    logger.debug("[query_phase] set thread_id=%s phase=%s", thread_id, phase)


async def get_query_phase(thread_id: str) -> Optional[str]:
    """Return the current processing phase from Redis, or ``None`` if absent.

    Args:
        thread_id: LangGraph UUID thread identifier.

    Returns:
        Phase string or ``None`` if the key has expired or was never set.
    """
    client = await _get_publish_client()
    val: Optional[str] = await client.get(_phase_key(thread_id))
    return val


async def delete_query_phase(thread_id: str) -> None:
    """Remove the phase key for *thread_id* when the query completes or is cancelled.

    Args:
        thread_id: LangGraph UUID thread identifier.
    """
    client = await _get_publish_client()
    await client.delete(_phase_key(thread_id))
    logger.debug("[query_phase] deleted thread_id=%s", thread_id)


__all__ = ["set_query_phase", "get_query_phase", "delete_query_phase"]
