"""Streaming subsystem configuration — single source of truth for the LLM ingest topic.

The only active Celery worker is ``celery-ingest``, which reads from the
``fin:llm:completions`` stream.  All other processing (LangGraph, market
data, trade signals) runs directly in the FastAPI event loop.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Celery broker / backend Redis DB indices
# ---------------------------------------------------------------------------

#: Celery task dispatch queue (Redis DB 1).
CELERY_BROKER_DB: int = 1
#: Celery task result store (Redis DB 2).
CELERY_BACKEND_DB: int = 2

# ---------------------------------------------------------------------------
# Celery worker process-level settings
# ---------------------------------------------------------------------------

_CELERY_WORKER_CONFIG_BASE: dict = {
    "task_serializer": "json",
    "accept_content": ["json"],
    "result_serializer": "json",
    "timezone": "UTC",
    "enable_utc": True,
    "task_track_started": True,
    "worker_hijack_root_logger": False,
    "worker_log_format": "%(asctime)s | %(levelname)-8s | Celery | %(message)s",
    "worker_task_log_format": "%(asctime)s | %(levelname)-8s | Celery/Task | %(message)s",
    "worker_prefetch_multiplier": 1,
    "broker_connection_retry_on_startup": True,
    # Prevent concurrent async_result.get() calls from sharing a single
    # backend Redis connection — each thread gets its own client instance.
    "result_backend_thread_safe": True,
}

# Windows: gevent pool.
_CELERY_WORKER_CONFIG_WINDOWS: dict = {
    "worker_heartbeat_timeout": 300,
    "heartbeat_interval": 30,
}

# Unix: prefork pool.
_CELERY_WORKER_CONFIG_UNIX: dict = {
    "worker_heartbeat_timeout": 60,
    "heartbeat_interval": 10,
    "worker_max_tasks_per_child": 500,
}

#: Platform-aware merged Celery worker config imported by ``celery_app.py``.
CELERY_WORKER_CONFIG: dict = {
    **_CELERY_WORKER_CONFIG_BASE,
    **(_CELERY_WORKER_CONFIG_WINDOWS if sys.platform == "win32" else _CELERY_WORKER_CONFIG_UNIX),
}


# ---------------------------------------------------------------------------
# Queue name — single queue for the one active worker
# ---------------------------------------------------------------------------

#: The only Celery queue: LLM ingest.
QUEUE_INGEST: str = "stream:ingest"


# ---------------------------------------------------------------------------
# Per-topic configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StreamTopicConfig:
    """All wiring parameters for a single Redis Streams topic.

    Attributes:
        stream_key:        Redis stream name (e.g. ``"fin:llm:completions"``).
        consumer_group:    Celery consumer group name.
        consumer_name:     Unique consumer ID within the group.
        human_key:         API-facing key used in HTTP/SSE endpoints.
        beat_interval:     Celery beat polling interval in seconds.
                           ``None`` means the task is on-demand (not beat-scheduled).
        fallback_interval: asyncio fallback poll interval in seconds.
        batch_size:        Maximum messages per batch read.
        max_retries:       Celery task max retry attempts on failure.
        retry_delay:       Celery task retry back-off in seconds.
        task_path:         Fully-qualified Celery task dotted name
                           (used for module include; ``None`` skips include).
        queue:             Celery queue name this task is dispatched to.
    """

    stream_key: str
    consumer_group: str
    consumer_name: str
    human_key: str
    beat_interval: float | None
    fallback_interval: float
    batch_size: int = 50
    max_retries: int = 3
    retry_delay: float = 5.0
    task_path: str | None = None
    queue: str = QUEUE_INGEST


# ---------------------------------------------------------------------------
# Stream key for per-token events (shard-routed, consumed by Centrifugo)
# ---------------------------------------------------------------------------

#: Redis stream name for raw LLM token events.  Shard-routed by thread_id so
#: each Centrifugo node reads only from the Redis shard it already backs.
STREAM_LLM_TOKENS: str = "fin:llm:tokens"


# ---------------------------------------------------------------------------
# Topic instances
# ---------------------------------------------------------------------------

#: LLM completions stream — one record per complete LLM call.
#: Written by ``invoke_llm`` after streaming all tokens.
#: ``beat_interval=None`` means on-demand only (invoke_llm is not beat-scheduled).
LLM_COMPLETIONS = StreamTopicConfig(
    stream_key="fin:llm:completions",
    consumer_group="celery-ingest",
    consumer_name="worker-llm-ingest",
    human_key="llm-completions",
    beat_interval=None,
    fallback_interval=10.0,
    batch_size=100,
    task_path="backend.streaming.workers.llm_ingest.invoke_llm",
    queue=QUEUE_INGEST,
)

#: PG persistence beat topic — reads ``fin:llm:completions`` and persists to DB.
#: Beat-scheduled every 10 seconds.  Replaces the old FastAPI background loop.
PG_PERSIST = StreamTopicConfig(
    stream_key="fin:llm:completions",
    consumer_group="pg-persist",
    consumer_name="worker-pg-persist",
    human_key="pg-persist",
    beat_interval=10.0,
    fallback_interval=10.0,
    batch_size=100,
    task_path="backend.streaming.workers.pg_persist.persist_llm_completions",
    queue=QUEUE_INGEST,
)

# ---------------------------------------------------------------------------
# Topic registry
# ---------------------------------------------------------------------------

#: All registered stream topics.
ALL_TOPICS: tuple[StreamTopicConfig, ...] = (LLM_COMPLETIONS, PG_PERSIST)

#: Topics that have a registered Celery worker module (``task_path`` is set).
ACTIVE_TOPICS: tuple[StreamTopicConfig, ...] = tuple(
    t for t in ALL_TOPICS if t.task_path is not None
)

__all__ = [
    "CELERY_BROKER_DB",
    "CELERY_BACKEND_DB",
    "CELERY_WORKER_CONFIG",
    "QUEUE_INGEST",
    "StreamTopicConfig",
    "STREAM_LLM_TOKENS",
    "LLM_COMPLETIONS",
    "PG_PERSIST",
    "ALL_TOPICS",
    "ACTIVE_TOPICS",
]
