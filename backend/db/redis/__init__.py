"""Redis database management sub-package.

Sub-modules:
    backend.db.redis.publisher           — append token events to a thread Redis Stream (stream_token)
    backend.db.redis.subscriber          — read token events from a thread Redis Stream (read_stream)
    backend.db.redis.query_phase         — ephemeral query-phase tracking (set/get/delete_query_phase)
    backend.db.redis.lifecycle_fanout    — single PG LISTEN → Redis PUBLISH fanout task (with leader election)
    backend.db.redis.lifecycle_subscriber — per-SSE Redis Pub/Sub lifecycle subscriber (read_lifecycle)
    backend.db.redis.watch_registry      — Redis-backed watch registry (register/unregister/get_watched_task)
    backend.db.redis.cancel_signal       — Redis Pub/Sub cancel signal (publish_cancel / run_cancel_listener)
    backend.db.redis.lock_manager        — systematic Redis lock management (RedisLock, cleanup_thread_session)

Pending-notify ack store (publisher):
    push_pending_notify   — record a pg_notify payload after commit
    ack_pending_notify    — mark a delivered event as received (HDEL)
    drain_pending_notify  — return+clear all unacked entries for recovery (returns DrainEntry list)
    clear_pending_notify  — wipe the hash on SSE teardown
    DrainEntry            — dataclass returned by drain_pending_notify
"""

from backend.db.redis.publisher import (
    DrainEntry,
    ack_pending_notify,
    clear_pending_notify,
    delete_stream,
    drain_pending_notify,
    push_pending_notify,
    stream_token,
)
from backend.db.redis.subscriber import read_stream
from backend.db.redis.query_phase import set_query_phase, get_query_phase, delete_query_phase
from backend.db.redis.lifecycle_fanout import lifecycle_pub_channel, run_lifecycle_fanout
from backend.db.redis.lifecycle_subscriber import read_lifecycle
from backend.db.redis.watch_registry import (
    register_watch,
    unregister_watch,
    get_watched_task,
    is_thread_watching,
)
from backend.db.redis.cancel_signal import publish_cancel, run_cancel_listener
from backend.db.redis.lock_manager import RedisLock, cleanup_thread_session

__all__ = [
    "stream_token",
    "delete_stream",
    "read_stream",
    "push_pending_notify",
    "ack_pending_notify",
    "drain_pending_notify",
    "clear_pending_notify",
    "DrainEntry",
    "set_query_phase",
    "get_query_phase",
    "delete_query_phase",
    "lifecycle_pub_channel",
    "run_lifecycle_fanout",
    "read_lifecycle",
    "register_watch",
    "unregister_watch",
    "get_watched_task",
    "is_thread_watching",
    "publish_cancel",
    "run_cancel_listener",
    "RedisLock",
    "cleanup_thread_session",
]

