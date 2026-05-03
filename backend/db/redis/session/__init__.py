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

backend.db.redis.session.query_status_ack_store
    Query-status lifecycle event ACK tracking (:func:`record_query_status_event`,
    :func:`ack_query_status_event`, :func:`get_unacked_phases`,
    :func:`increment_phase_retry`, :func:`delete_query_status_ack`).

backend.db.redis.session.cancel_signal
    Cross-instance asyncio.Task cancellation via Redis Pub/Sub
    (:func:`publish_cancel`, :func:`run_cancel_listener`).

backend.db.redis.session.pause_signal
    Redis-backed pause signal for LangGraph interrupt-based pause/resume
    (:func:`set_pause_signal`, :func:`check_and_consume_pause_signal`,
    :func:`delete_pause_signal`).

backend.db.redis.session.perf_stable_signal
    Redis-backed stable signal for concurrent perf-test sessions
    (:func:`set_perf_stable`, :func:`check_and_consume_perf_stable`).

backend.db.redis.session.stream_sched
    Redis state management for the priority-based concurrent stream scheduler.
    Tracks per-run stream state (produced, elapsed, inflight, done) and provides
    coordinator lock/rendezvous helpers used by the FastAPI coordinator and the
    Celery slice tasks.
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
from backend.db.redis.session.pause_signal import (
    check_and_consume_pause_signal,
    delete_pause_signal,
    set_pause_signal,
)
from backend.db.redis.session.perf_stable_signal import (
    check_and_consume_perf_stable,
    set_perf_stable,
)
from backend.db.redis.session.query_status_ack_store import (
    ack_query_status_event,
    delete_query_status_ack,
    get_stream_id_for_thread,
    get_unacked_phases,
    increment_phase_retry,
    record_query_status_event,
    store_stream_id_for_thread,
)

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
    "set_pause_signal",
    "check_and_consume_pause_signal",
    "delete_pause_signal",
    "set_perf_stable",
    "check_and_consume_perf_stable",
    "record_query_status_event",
    "ack_query_status_event",
    "get_unacked_phases",
    "increment_phase_retry",
    "delete_query_status_ack",
    "store_stream_id_for_thread",
    "get_stream_id_for_thread",
]
