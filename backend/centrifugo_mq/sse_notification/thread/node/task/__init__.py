"""centrifugo_mq.sse_notification.thread.node.task — task-scope SSE notification.

Publishes a task-level SSE event then awaits an ACK from the frontend via
Redis BLPOP.  On NACK or timeout a ``task_status: failed`` event is published
automatically so the frontend always receives a terminal state.

Implementation split
--------------------
notify.py — notify() implementation
"""

from backend.centrifugo_mq.sse_notification.thread.node.task.notify import notify

__all__ = ["notify"]
