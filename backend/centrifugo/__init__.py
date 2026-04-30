"""centrifugo — Centrifugo real-time messaging integration.

Publishes lifecycle and token events to Centrifugo WebSocket channels
instead of Redis Pub/Sub / Redis Streams + SSE.

Shard routing
-------------
Uses the same SHA-256 ``thread_id`` hash as the Redis router so that
the Centrifugo node chosen by FastAPI is always backed by the Redis node
that owns the thread's session keys.  The frontend is told which
Centrifugo WebSocket endpoint to connect to via the token endpoint:

    GET /api/v1/centrifugo/token?thread_id=<uuid>
    → {"ws_url": "ws://kong/centrifugo-0/connection/websocket",
       "connection_token": "<JWT>",
       "subscription_token": "<JWT>"}

Channel naming
--------------
All events for a thread travel on a single channel: ``thread:{thread_id}``.
The ``thread`` namespace (configured in Centrifugo) has history enabled so
reconnecting clients recover missed events without a server-side drain cycle.

Public API
----------
:func:`~backend.centrifugo.client.publish_to_channel`  — fire-and-forget publish.
:func:`~backend.centrifugo.tokens.make_connection_token` — connection JWT.
:func:`~backend.centrifugo.tokens.make_subscription_token` — subscription JWT.
:func:`~backend.centrifugo.client.get_shard_index`     — shard index for a thread_id.
"""

from backend.centrifugo.client import get_shard_index, publish_to_channel
from backend.centrifugo.tokens import make_connection_token, make_subscription_token

__all__ = [
    "publish_to_channel",
    "make_connection_token",
    "make_subscription_token",
    "get_shard_index",
]
