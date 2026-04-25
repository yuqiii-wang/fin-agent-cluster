"""Redis Streams sub-package — token I/O and pending-notify bookkeeping.

Modules
-------
backend.db.redis.streams.publisher
    :func:`stream_token` — XADD token to per-thread stream.
    Pending-notify helpers: :func:`push_pending_notify`, :func:`ack_pending_notify`,
    :func:`drain_pending_notify`, :func:`clear_pending_notify`.

backend.db.redis.streams.subscriber
    :func:`read_stream` — async context manager; XREAD BLOCK pump onto a Queue.
"""

from backend.db.redis.streams.publisher import (
    DrainEntry,
    ack_pending_notify,
    clear_pending_notify,
    delete_stream,
    drain_pending_notify,
    push_pending_notify,
    stream_key,
    stream_token,
)
from backend.db.redis.streams.subscriber import read_stream

__all__ = [
    "stream_token",
    "stream_key",
    "delete_stream",
    "push_pending_notify",
    "ack_pending_notify",
    "drain_pending_notify",
    "clear_pending_notify",
    "DrainEntry",
    "read_stream",
]
