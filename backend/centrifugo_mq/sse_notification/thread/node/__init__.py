"""centrifugo_mq.sse_notification.thread.node -- node-scope SSE notification.

Publishes a node-level SSE event then awaits an ACK from the frontend via
Redis BLPOP.  On NACK or timeout a ``notification_failed`` event is published
automatically.

Implementation split
--------------------
notify.py -- notify() implementation
"""

from backend.centrifugo_mq.sse_notification.thread.node.notify import notify

__all__ = ["notify"]
