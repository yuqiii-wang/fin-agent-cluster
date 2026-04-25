"""Redis database management sub-package.

Sub-packages:
    backend.db.redis.streams       — Redis Streams token I/O and pending-notify bookkeeping
    backend.db.redis.lifecycle     — Redis Pub/Sub lifecycle subscriber
    backend.db.redis.session       — per-session state (query phase, watch registry, task ACK, cancel)
    backend.db.redis.lock_manager  — RedisLock + canonical session-key cleanup

Top-level:
    backend.db.redis.router        — shard-consistent routing (get_redis_router)

Pending-notify ack store (streams.publisher):
    push_pending_notify   — record a lifecycle payload after commit
    ack_pending_notify    — mark a delivered event as received (HDEL)
    drain_pending_notify  — return+clear all unacked entries for recovery (returns DrainEntry list)
    clear_pending_notify  — wipe the hash on SSE teardown
    DrainEntry            — dataclass returned by drain_pending_notify
"""

from backend.db.redis.streams.publisher import (
    DrainEntry,
    ack_pending_notify,
    clear_pending_notify,
    delete_stream,
    drain_pending_notify,
    push_pending_notify,
    stream_token,
)
from backend.db.redis.streams.subscriber import read_stream
from backend.db.redis.session.query_phase import set_query_phase, get_query_phase, delete_query_phase
from backend.db.redis.lifecycle.subscriber import lifecycle_pub_channel, read_lifecycle
from backend.db.redis.session.watch_registry import (
    register_watch,
    unregister_watch,
    get_watched_task,
    is_thread_watching,
)
from backend.db.redis.session.cancel_signal import publish_cancel, run_cancel_listener
from backend.db.redis.lock_manager import RedisLock, cleanup_thread_session
from backend.db.redis.router import RedisRouter, get_redis_router
from backend.db.redis.session.task_ack_store import (
    record_task_step,
    ack_task_step,
    increment_task_step_retry,
)

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
    "read_lifecycle",
    "register_watch",
    "unregister_watch",
    "get_watched_task",
    "is_thread_watching",
    "publish_cancel",
    "run_cancel_listener",
    "RedisLock",
    "cleanup_thread_session",
    "RedisRouter",
    "get_redis_router",
    "record_task_step",
    "ack_task_step",
    "increment_task_step_retry",
]
