"""Redis Streams MQ/buffer layer for fin-trading real-time events.

This package replaces the ephemeral Redis Pub/Sub pattern with a persistent,
consumer-group–aware Redis Streams topology.  Celery workers batch-consume each
stream while the FastAPI layer exposes HTTP and SSE bridges for external clients
(routed through Kong).

Stream topology
---------------
Stream name                  Consumer groups              Publishers
fin:graph:events             celery-graph                 graph nodes
fin:market:ticks             celery-market, analytics     resource_api.quant_api
fin:news:enriched            celery-news, analytics       resource_api.news_api
fin:signals:trade            celery-signals, analytics    decision_maker agent
fin:llm:completions          celery-llm, analytics        llm.factory callback

Sub-modules
-----------
config      — StreamTopicConfig + all topic instances (single source of truth)
streams     — RedisStreamClient + stream operations (xadd, xread, …)
schemas     — Pydantic message models for each stream topic
celery_app  — Celery application factory
workers     — Celery consumer tasks (graph_events, market_data, signals)
"""

from backend.streaming.config import (
    ACTIVE_TOPICS,
    ALL_TOPICS,
    GRAPH_EVENTS,
    LLM_COMPLETIONS,
    MARKET_TICKS,
    NEWS_ENRICHED,
    TRADE_SIGNALS,
    StreamTopicConfig,
)
from backend.streaming.fallback import celery_workers_available, start_fallback_workers
from backend.streaming.log_filters import CeleryTaskSummaryFilter
from backend.streaming.streams import (
    GROUP_CELERY_GRAPH,
    GROUP_CELERY_MARKET,
    GROUP_CELERY_NEWS,
    GROUP_CELERY_SIGNALS,
    STREAM_GRAPH_EVENTS,
    STREAM_LLM_COMPLETIONS,
    STREAM_MARKET_TICKS,
    STREAM_NEWS_ENRICHED,
    STREAM_TRADE_SIGNALS,
    ensure_group,
    xack,
    xadd,
    xlen,
    xread,
    xread_group,
)

__all__ = [
    # Config — topic wiring
    "StreamTopicConfig",
    "GRAPH_EVENTS",
    "MARKET_TICKS",
    "TRADE_SIGNALS",
    "NEWS_ENRICHED",
    "LLM_COMPLETIONS",
    "ALL_TOPICS",
    "ACTIVE_TOPICS",
    # Celery / fallback control
    "celery_workers_available",
    "start_fallback_workers",
    # Log filters
    "CeleryTaskSummaryFilter",
    # Stream name constants (aliases — derived from config)
    "STREAM_GRAPH_EVENTS",
    "STREAM_MARKET_TICKS",
    "STREAM_NEWS_ENRICHED",
    "STREAM_TRADE_SIGNALS",
    "STREAM_LLM_COMPLETIONS",
    # Consumer group constants (aliases — derived from config)
    "GROUP_CELERY_GRAPH",
    "GROUP_CELERY_MARKET",
    "GROUP_CELERY_NEWS",
    "GROUP_CELERY_SIGNALS",
    # Stream operations
    "xadd",
    "xread",
    "xread_group",
    "xack",
    "xlen",
    "ensure_group",
]
