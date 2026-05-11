"""centrifugo_mq.sse_notification — SSE lifecycle notification helpers.

Scope-specific ``notify`` helpers live in sub-packages:

* :mod:`backend.centrifugo_mq.sse_notification.thread`           — thread-scope
* :mod:`backend.centrifugo_mq.sse_notification.thread.node`      — node-scope
* :mod:`backend.centrifugo_mq.sse_notification.thread.node.task` — task-scope

Each ``notify`` call publishes a Centrifugo SSE event and then awaits an ACK
from the frontend via Redis BLPOP (:mod:`backend.db.redis.session.notify_ack_store`).
On NACK or timeout a failed event is published automatically.
"""

__all__: list[str] = []
