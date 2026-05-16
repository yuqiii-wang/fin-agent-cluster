"""centrifugo — Centrifugo real-time messaging integration.

Publishes lifecycle and token events to Centrifugo WebSocket channels
instead of Redis Pub/Sub / Redis Streams + SSE.

Shard routing
-------------
Uses the same SHA-256 ``thread_id`` hash as the Redis router so that
the Centrifugo node chosen by FastAPI is always backed by the Redis node
that owns the thread's session keys.  The frontend is told which
Centrifugo WebSocket endpoint to connect to via the token endpoint:

    GET /api/v1/centrifugo/llm-token?thread_id=<uuid>
    → {"ws_url": "ws://kong/centrifugo-llm-0/connection/websocket",
       "connection_token": "<JWT>",
       "subscription_token": "<JWT>"}

Channel naming
--------------
All events for a thread travel on a single channel: ``thread:{thread_id}``.
The ``thread`` namespace (configured in Centrifugo) has history enabled so
reconnecting clients recover missed events without a server-side drain cycle.

Scope-based Public API
-----------------------
All four publish functions route to the same ``thread:{thread_id}`` channel;
the scope names make call-sites explicit about which lifecycle level the event
belongs to and allow future per-scope differentiation.

:func:`~backend.centrifugo.client.publish_thread_event`  — thread-level events.
:func:`~backend.centrifugo.client.publish_node_event`    — node-level events.
:func:`~backend.centrifugo.client.publish_task_event`    — task-level events.
:func:`~backend.centrifugo.client.publish_stream_event`  — stream-level events.
:func:`~backend.centrifugo.tokens.make_connection_token` — connection JWT.
:func:`~backend.centrifugo.tokens.make_subscription_token` — subscription JWT.
:func:`~backend.centrifugo.client.get_shard_index`       — shard index for a thread_id.
"""

from backend.auth.jwt import make_connection_token, make_subscription_token
from backend.centrifugo_mq.client import (
    get_shard_index,
    get_sse_shard_index,
    publish_node_event,
    publish_stream_event,
    publish_task_event,
    publish_thread_event,
)
from backend.centrifugo_mq.publish_proxy import handle_ack_publish

__all__ = [
    "publish_thread_event",
    "publish_node_event",
    "publish_task_event",
    "publish_stream_event",
    "make_connection_token",
    "make_subscription_token",
    "get_shard_index",
    "get_sse_shard_index",
    "handle_ack_publish",
]
