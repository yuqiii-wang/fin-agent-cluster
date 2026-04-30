"""Redis database management sub-package.

Sub-packages:
    backend.db.redis.streams       -- Redis Streams token publisher (via Centrifugo)
    backend.db.redis.session       -- per-session state (query phase, watch registry, task ACK, cancel)
    backend.db.redis.lock_manager  -- RedisLock + canonical session-key cleanup

Top-level:
    backend.db.redis.router        -- shard-consistent routing (get_redis_router)
"""

from backend.db.redis.streams.publisher import (
    stream_token,
)
from backend.db.redis.session.query_phase import set_query_phase, get_query_phase, delete_query_phase
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
    "set_query_phase",
    "get_query_phase",
    "delete_query_phase",
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
