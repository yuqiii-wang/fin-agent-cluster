"""Celery task package — worker engine, config, and task delegation.

Sub-modules
-----------
config          -- StreamTopicConfig, queue helpers (get_ondemand_queue, all_ondemand_queues)
log_filters     -- CeleryTaskSummaryFilter
celery_engine   -- Celery application factory (celery_engine)
workers         -- task_delegation helpers (delegate_completion, delegate_stream)
                   and worker Celery tasks (completion_task, stream_task)
"""

from backend.celery_task.config import (
    ACTIVE_TOPICS,
    StreamTopicConfig,
    get_ondemand_queue,
    all_ondemand_queues,
)
from backend.celery_task.log_filters import CeleryTaskSummaryFilter
from backend.celery_task.celery_engine import celery_engine
from backend.celery_task.workers.task_delegation import delegate_completion, delegate_stream

__all__ = [
    # Config
    "StreamTopicConfig",
    "ACTIVE_TOPICS",
    "get_ondemand_queue",
    "all_ondemand_queues",
    # Log filters
    "CeleryTaskSummaryFilter",
    # Celery engine
    "celery_engine",
    # Task delegation
    "delegate_completion",
    "delegate_stream",
]
