"""Celery task configuration — broker DBs, worker settings, and queue helpers.

All on-demand tasks that carry a ``thread_id`` (completion and stream workers)
are dispatched to a queue determined by ``SHA-256(thread_id) % shard_count``
so work for the same logical session consistently lands on the same Celery
worker, improving cache locality and reducing cross-worker state contention.

Shard routing
-------------
The Celery **broker** is always pinned to shard 0 of the Redis cluster (a
Celery infrastructure constraint — the broker URL is configured once at
process start and cannot vary per task).  Within that broker, named queues
act as logical shards: ``celery_ondemand_0``, ``celery_ondemand_1``, …

Workers listen on all ``celery_ondemand_*`` queues; tasks land on the queue
whose index matches ``SHA-256(thread_id) % n_shards``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Optional

from backend.config import get_settings

# ---------------------------------------------------------------------------
# Redis DB indices used by the Celery application
# ---------------------------------------------------------------------------

#: Redis DB index for the Celery task broker (queue transport).
CELERY_BROKER_DB: int = 1

#: Redis DB index for the Celery result backend (task result storage).
CELERY_BACKEND_DB: int = 2

# ---------------------------------------------------------------------------
# Celery worker process configuration
# ---------------------------------------------------------------------------

CELERY_WORKER_CONFIG: dict = {
    "task_serializer": "json",
    "accept_content": ["json"],
    "result_serializer": "json",
    "task_track_started": True,
    # Process one task at a time — avoids overloading a single worker with
    # concurrent LLM calls that are already async internally.
    "worker_prefetch_multiplier": 1,
    # Acknowledge only after successful return so failed tasks can be retried.
    "task_acks_late": True,
    "timezone": "UTC",
    "enable_utc": True,
}

# ---------------------------------------------------------------------------
# Stream topic config (for beat-scheduled polling workers)
# ---------------------------------------------------------------------------

@dataclass
class StreamTopicConfig:
    """Configuration for a Redis Stream consumer topic.

    Attributes:
        human_key:     Short human-readable key used in beat-schedule naming.
        task_path:     Fully-qualified Celery task function path.
        queue:         Celery queue name the beat schedule submits to.
        beat_interval: Beat schedule interval in seconds.  ``None`` means the
                       topic is on-demand only and excluded from beat schedule.
    """

    human_key: str
    task_path: str
    queue: str
    beat_interval: Optional[float] = field(default=None)


#: Topics registered for beat-scheduled polling.  Currently empty — all tasks
#: (completion and stream) are dispatched on-demand with thread_id routing.
ACTIVE_TOPICS: list[StreamTopicConfig] = []

# ---------------------------------------------------------------------------
# On-demand queue helpers — thread_id → queue name
# ---------------------------------------------------------------------------

#: Prefix used for all on-demand task queues.
ONDEMAND_QUEUE_PREFIX: str = "celery_ondemand"


def get_ondemand_queue(thread_id: str) -> str:
    """Return the Celery queue name for an on-demand task carrying *thread_id*.

    Uses ``SHA-256(thread_id) % n_shards`` — the same formula as
    :class:`~backend.db.redis.router.RedisRouter` and Centrifugo routing —
    so all layers for the same session consistently target the same shard.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        Queue name string, e.g. ``"celery_ondemand_0"``.
    """
    settings = get_settings()
    n = len(settings.DATABASE_REDIS_NODES) or 1
    digest = int(hashlib.sha256(thread_id.encode()).hexdigest(), 16)
    shard = digest % n
    return f"{ONDEMAND_QUEUE_PREFIX}_{shard}"


def all_ondemand_queues() -> list[str]:
    """Return the full list of on-demand queue names across all shards.

    Used by the worker startup command to pass ``-Q queue0,queue1,...`` so
    workers listen on every shard queue.

    Returns:
        List of queue name strings ordered by shard index.
    """
    settings = get_settings()
    n = len(settings.DATABASE_REDIS_NODES) or 1
    return [f"{ONDEMAND_QUEUE_PREFIX}_{i}" for i in range(n)]


__all__ = [
    "CELERY_BROKER_DB",
    "CELERY_BACKEND_DB",
    "CELERY_WORKER_CONFIG",
    "StreamTopicConfig",
    "ACTIVE_TOPICS",
    "ONDEMAND_QUEUE_PREFIX",
    "get_ondemand_queue",
    "all_ondemand_queues",
]
