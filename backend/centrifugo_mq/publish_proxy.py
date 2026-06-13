"""centrifugo.publish_proxy -- Centrifugo publish-proxy ACK handler.

Receives publish-proxy requests forwarded by Centrifugo when a frontend
client calls ``sub.publish(data)`` on the ``thread:{thread_id}`` channel.

The only client publication currently supported is ``event: "ack"``.
It signals the Redis BLPOP waiter that is blocking the backend SSE
``notify()`` call, replacing the previous round-trip via ``cf.rpc()``.

The handler returns ``skip_history=True`` so ACK publications are NOT
stored in Centrifugo channel history and never replayed to reconnecting
clients.  This keeps the thread history clean (server events only).
"""

from __future__ import annotations

import logging
from typing import Any

from backend.db.redis.session.notify_ack_store import signal_notify_ack

logger = logging.getLogger(__name__)


async def handle_ack_publish(thread_id: str, data: dict[str, Any]) -> None:
    """Process a client-published ACK event.

    Extracts ``ack_key`` from the published data and unblocks the Redis BLPOP
    waiter that the backend SSE ``notify()`` call is blocking on.

    Args:
        thread_id: LangGraph thread UUID extracted from the Centrifugo channel.
        data:      Published data dict from the frontend; must contain ``ack_key``.
    """
    ack_key: str = data.get("ack_key", "")
    if not ack_key:
        logger.warning(
            "[publish_proxy] missing ack_key thread_id=%s data=%s", thread_id, data
        )
        return
    await signal_notify_ack(thread_id, ack_key)
