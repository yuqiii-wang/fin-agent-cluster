"""Per-session Redis state sub-package.

Modules
-------
backend.db.redis.session.query_phase
    Ephemeral query-phase tracking (:func:`set_query_phase`,
    :func:`get_query_phase`, :func:`delete_query_phase`).

backend.db.redis.session.watch_registry
    Redis-backed SSE watch registry (:func:`register_watch`,
    :func:`unregister_watch`, :func:`get_watched_task`,
    :func:`is_thread_watching`).

backend.db.redis.session.task_ack_store
    SSE task-delivery ACK bookkeeping (:func:`record_task_step`,
    :func:`ack_task_step`, :func:`increment_task_step_retry`).

backend.db.redis.session.cancel_signal
    Cross-instance asyncio.Task cancellation via Redis Pub/Sub
    (:func:`publish_cancel`, :func:`run_cancel_listener`).
"""

from backend.db.redis.session.query_phase import (
    delete_query_phase,
    get_query_phase,
    set_query_phase,
)
from backend.db.redis.session.watch_registry import (
    get_watched_task,
    is_thread_watching,
    register_watch,
    unregister_watch,
)
from backend.db.redis.session.task_ack_store import (
    ack_task_step,
    increment_task_step_retry,
    record_task_step,
)
from backend.db.redis.session.cancel_signal import publish_cancel, run_cancel_listener

__all__ = [
    "set_query_phase",
    "get_query_phase",
    "delete_query_phase",
    "register_watch",
    "unregister_watch",
    "get_watched_task",
    "is_thread_watching",
    "record_task_step",
    "ack_task_step",
    "increment_task_step_retry",
    "publish_cancel",
    "run_cancel_listener",
]
