"""Pydantic message schemas for Redis Streams topics.

Every stream has a dedicated message model.  All models inherit from
``BaseStreamMessage`` which adds a UUID event ID and UTC timestamp.

When consuming, reconstruct the model with ``Model.model_validate(fields)``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class StreamKey(str, Enum):
    """Human-readable stream key names used in the HTTP API.

    These values map to actual Redis stream names via
    ``backend.streaming.streams.STREAM_KEY_MAP``.
    """

    GRAPH_EVENTS = "graph-events"
    MARKET_TICKS = "market-ticks"
    TRADE_SIGNALS = "trade-signals"
    NEWS_ENRICHED = "news-enriched"
    LLM_COMPLETIONS = "llm-completions"


class BaseStreamMessage(BaseModel):
    """Common envelope fields shared by all stream message types.

    Attributes:
        event_id: UUID4 string — unique identifier for idempotent processing.
        ts:       UTC timestamp when the message was produced.
    """

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Graph events — emitted by LangGraph nodes
# ---------------------------------------------------------------------------


class GraphEventMessage(BaseStreamMessage):
    """A single agent-task lifecycle event from a LangGraph node.

    Mirrors the existing Redis Pub/Sub payload so graph nodes can switch to
    :func:`~backend.streaming.streams.xadd` without changing their emitted
    data shape.

    Attributes:
        thread_id:   LangGraph thread UUID.
        event_type:  ``started | token | completed | failed | done | ping``.
        task_id:     Database row ID of the associated AgentTask (if any).
        node_name:   Agent node emitting the event.
        task_key:    Sub-task key string (e.g. ``'fetch_ohlcv'``).
        data:        Arbitrary event payload dict.
    """

    thread_id: str
    event_type: str
    task_id: Optional[int] = None
    node_name: Optional[str] = None
    task_key: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Market data — emitted by resource_api.quant_api
# ---------------------------------------------------------------------------


class OHLCVBarMessage(BaseModel):
    """One OHLCV bar within a MarketTickMessage.

    Attributes:
        t:    Bar timestamp (ISO-8601 string or epoch seconds).
        o:    Open price.
        h:    High price.
        l:    Low price.
        c:    Close price.
        v:    Volume.
    """

    t: str
    o: float
    h: float
    l: float
    c: float
    v: float


class MarketTickMessage(BaseStreamMessage):
    """Market data fetched by the quant resource API.

    Attributes:
        symbol:      Canonical ticker symbol (upper-case).
        source:      Provider name (``'yfinance'``, ``'akshare'``, etc.).
        method:      Fetch method (``'ohlcv'``, ``'quote'``, etc.).
        thread_id:   Originating LangGraph thread (may be empty for batch jobs).
        node_name:   Agent node that triggered the fetch.
        bar_count:   Number of bars in this message.
        bars:        OHLCV bar list serialised as JSON string.
    """

    symbol: str
    source: str
    method: str
    thread_id: Optional[str] = None
    node_name: Optional[str] = None
    bar_count: int = 0
    bars: str = "[]"  # JSON-encoded list[OHLCVBarMessage]


# ---------------------------------------------------------------------------
# Trading signals — emitted by the decision_maker agent
# ---------------------------------------------------------------------------


class TradeSignalMessage(BaseStreamMessage):
    """A trade recommendation produced by the decision-maker agent.

    Attributes:
        thread_id:   Originating query thread.
        symbol:      Target ticker symbol.
        signal:      ``buy | sell | hold``.
        confidence:  Model confidence in [0, 1].
        reasoning:   Short textual justification.
        indicators:  Snapshot of indicator values used for the decision.
    """

    thread_id: str
    symbol: str
    signal: str  # buy | sell | hold
    confidence: float = 0.0
    reasoning: str = ""
    indicators: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# News enrichment — emitted by resource_api.news_api
# ---------------------------------------------------------------------------


class NewsEnrichmentMessage(BaseStreamMessage):
    """A batch of news articles fetched by the news resource API.

    Attributes:
        thread_id:     Originating LangGraph thread (may be empty).
        symbol:        Ticker the news relates to (if symbol-scoped query).
        query:         Free-text query used for the search.
        source:        Provider name (``'yfinance'``, ``'alpha_vantage'``, etc.).
        article_count: Number of articles in this message.
        articles:      Article list serialised as JSON string.
    """

    thread_id: Optional[str] = None
    symbol: Optional[str] = None
    query: Optional[str] = None
    source: str
    article_count: int = 0
    articles: str = "[]"  # JSON-encoded list[dict]


# ---------------------------------------------------------------------------
# LLM completion events — emitted by llm.factory callback
# ---------------------------------------------------------------------------


class LLMCompletionMessage(BaseStreamMessage):
    """Token usage and latency record for a single LLM completion.

    Attributes:
        thread_id:         Originating LangGraph thread.
        provider:          LLM provider name (``'ollama'``, ``'ark'``, etc.).
        model:             Model identifier string.
        task_key:          Agent sub-task that triggered the completion.
        node_name:         Agent node name.
        prompt_tokens:     Input token count.
        completion_tokens: Output token count.
        total_tokens:      Sum of prompt + completion tokens.
        latency_ms:        Wall-clock time from request to first token.
    """

    thread_id: Optional[str] = None
    provider: str = ""
    model: str = ""
    task_key: Optional[str] = None
    node_name: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0


# ---------------------------------------------------------------------------
# HTTP API response models
# ---------------------------------------------------------------------------


class StreamInfoResponse(BaseModel):
    """Metadata about a stream returned by the info endpoint.

    Attributes:
        stream_key: Human-readable key.
        stream:     Internal Redis stream name.
        length:     Current number of entries.
    """

    stream_key: StreamKey
    stream: str
    length: int
