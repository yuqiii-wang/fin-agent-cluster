"""Redis Streams MQ/buffer layer -- LLM completion ingest.

The only active stream is ``fin:llm:completions``, consumed by the
``celery-ingest`` worker.  All LangGraph execution, market data fetching,
and trade signal processing runs directly in the FastAPI event loop.

Sub-modules
-----------
config      -- StreamTopicConfig + LLM_COMPLETIONS topic (single source of truth)
streams     -- Redis stream operations (xadd, xread, ...)
schemas     -- Pydantic message models
celery_app  -- Celery application factory
workers     -- celery-ingest consumer task (llm_ingest)
fallback    -- FastAPI-native fallback when celery-ingest is not running
errors      -- Streaming worker and domain error code registries
"""

from backend.streaming.config import (
    ACTIVE_TOPICS,
    ALL_TOPICS,
    LLM_COMPLETIONS,
    QUEUE_INGEST,
    StreamTopicConfig,
)
from backend.streaming.fallback import celery_workers_available, start_fallback_workers
from backend.streaming.log_filters import CeleryTaskSummaryFilter
from backend.streaming.streams import (
    GROUP_CELERY_INGEST,
    STREAM_LLM_COMPLETIONS,
    ensure_group,
    xack,
    xadd,
    xlen,
    xread,
    xread_group,
)

__all__ = [
    # Config -- topic wiring
    "StreamTopicConfig",
    "LLM_COMPLETIONS",
    "QUEUE_INGEST",
    "ALL_TOPICS",
    "ACTIVE_TOPICS",
    # Celery / fallback control
    "celery_workers_available",
    "start_fallback_workers",
    # Log filters
    "CeleryTaskSummaryFilter",
    # Stream name constants
    "STREAM_LLM_COMPLETIONS",
    # Consumer group constants
    "GROUP_CELERY_INGEST",
    # Stream operations
    "xadd",
    "xread",
    "xread_group",
    "xack",
    "xlen",
    "ensure_group",
]
