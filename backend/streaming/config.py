"""Streaming subsystem configuration — single source of truth for all topic wiring.

Each Redis Stream topic is described by a :class:`StreamTopicConfig` that
bundles the stream name, consumer group, worker settings, and schedule.
``celery_app.py`` derives ``include`` and ``beat_schedule`` from
:data:`ACTIVE_TOPICS`; ``fallback.py`` uses ``fallback_interval`` for asyncio
poll loops; ``streams.py`` builds consumer-group maps from :data:`ALL_TOPICS`.
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
    # Prefetch = 1 prevents workers from hoarding tasks before the previous batch finishes.
    "worker_prefetch_multiplier": 1,
    "broker_connection_retry_on_startup": True,
}

# Windows: gevent pool — generous heartbeat because greenlets may not respond immediately.
_CELERY_WORKER_CONFIG_WINDOWS: dict = {
    "worker_heartbeat_timeout": 300,   # 5 min
    "heartbeat_interval": 30,
}

# Unix: prefork pool — recycle workers periodically to cap memory growth.
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
# Per-topic configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StreamTopicConfig:
    """All wiring parameters for a single Redis Streams topic.

    Centralising these here makes the producer/consumer relationship explicit
    and easy to trace during debugging.  To add a new topic, create a new
    instance below and append it to :data:`ALL_TOPICS`.

    Attributes:
        stream_key:        Redis stream name (e.g. ``"fin:graph:events"``).
        consumer_group:    Celery consumer group name (e.g. ``"celery-graph"``).
        consumer_name:     Unique consumer ID within the group
                           (e.g. ``"worker-graph-events"``).
        human_key:         API-facing key used in HTTP/SSE endpoints
                           (e.g. ``"graph-events"``).
        beat_interval:     Celery beat polling interval in seconds.
        fallback_interval: asyncio fallback poll interval in seconds.
        batch_size:        Maximum messages per ``consume_batch`` call.
        max_retries:       Celery task max retry attempts on failure.
        retry_delay:       Celery task retry back-off in seconds.
        task_path:         Fully-qualified Celery task dotted name used to
                           register the beat entry.  ``None`` means no Celery
                           worker is implemented yet — the topic is omitted
                           from the beat schedule and worker include list.
    """

    stream_key: str
    consumer_group: str
    consumer_name: str
    human_key: str
    beat_interval: float
    fallback_interval: float
    batch_size: int = 50
    max_retries: int = 3
    retry_delay: float = 5.0
    task_path: str | None = None


# ---------------------------------------------------------------------------
# Topic instances  ← edit here to tune or add streams
# ---------------------------------------------------------------------------

#: LangGraph node lifecycle events (started / token / completed / failed).
GRAPH_EVENTS = StreamTopicConfig(
    stream_key="fin:graph:events",
    consumer_group="celery-graph",
    consumer_name="worker-graph-events",
    human_key="graph-events",
    beat_interval=2.0,       # low latency — drives SSE UI events
    fallback_interval=2.0,
    task_path="backend.streaming.workers.graph_events.consume_batch",
)

#: OHLCV market data published by resource_api.quant_api.
MARKET_TICKS = StreamTopicConfig(
    stream_key="fin:market:ticks",
    consumer_group="celery-market",
    consumer_name="worker-market-data",
    human_key="market-ticks",
    beat_interval=5.0,
    fallback_interval=5.0,
    retry_delay=10.0,
    task_path="backend.streaming.workers.market_data.consume_batch",
)

#: Trade recommendations produced by the decision_maker agent.
TRADE_SIGNALS = StreamTopicConfig(
    stream_key="fin:signals:trade",
    consumer_group="celery-signals",
    consumer_name="worker-signals",
    human_key="trade-signals",
    beat_interval=5.0,
    fallback_interval=5.0,
    retry_delay=10.0,
    task_path="backend.streaming.workers.signals.consume_batch",
)

#: News articles fetched by resource_api.news_api (no worker yet).
NEWS_ENRICHED = StreamTopicConfig(
    stream_key="fin:news:enriched",
    consumer_group="celery-news",
    consumer_name="worker-news",
    human_key="news-enriched",
    beat_interval=10.0,
    fallback_interval=10.0,
)

#: LLM token usage records from llm.factory (no worker yet).
LLM_COMPLETIONS = StreamTopicConfig(
    stream_key="fin:llm:completions",
    consumer_group="celery-llm",
    consumer_name="worker-llm",
    human_key="llm-completions",
    beat_interval=10.0,
    fallback_interval=10.0,
)

# ---------------------------------------------------------------------------
# Topic registry
# ---------------------------------------------------------------------------

#: Every registered stream topic (active and pending).
ALL_TOPICS: tuple[StreamTopicConfig, ...] = (
    GRAPH_EVENTS,
    MARKET_TICKS,
    TRADE_SIGNALS,
    NEWS_ENRICHED,
    LLM_COMPLETIONS,
)

#: Topics that have a registered Celery worker (``task_path`` is set).
#: Used by ``celery_app.py`` to build the ``include`` list and beat schedule.
ACTIVE_TOPICS: tuple[StreamTopicConfig, ...] = tuple(
    t for t in ALL_TOPICS if t.task_path is not None
)

__all__ = [
    "CELERY_BROKER_DB",
    "CELERY_BACKEND_DB",
    "CELERY_WORKER_CONFIG",
    "StreamTopicConfig",
    "GRAPH_EVENTS",
    "MARKET_TICKS",
    "TRADE_SIGNALS",
    "NEWS_ENRICHED",
    "LLM_COMPLETIONS",
    "ALL_TOPICS",
    "ACTIVE_TOPICS",
]
