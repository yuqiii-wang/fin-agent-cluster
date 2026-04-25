"""Lifecycle event sub-package — Redis Pub/Sub publish and subscribe.

Modules
-------
backend.db.redis.lifecycle.subscriber
    :func:`lifecycle_pub_channel` — returns the Redis Pub/Sub channel name for a thread.
    :func:`read_lifecycle` — async context manager; subscribes to the per-thread
    Redis Pub/Sub channel and pumps JSON payloads onto a Queue.
"""

from backend.db.redis.lifecycle.subscriber import lifecycle_pub_channel, read_lifecycle

__all__ = [
    "lifecycle_pub_channel",
    "read_lifecycle",
]
