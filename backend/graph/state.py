"""Shared state schema for the financial analysis LangGraph workflow."""

from __future__ import annotations

from typing import Annotated, TypedDict
from typing import NotRequired


def _merge_lists(a: list[str], b: list[str]) -> list[str]:
    """Reducer that concatenates two step-log lists across parallel branches."""
    return a + b


class PerfTestState(TypedDict):
    """Minimal state for the single-node streaming performance-test graph."""

    thread_id: str
    total_tokens: int
    timeout_secs: int
    pub_mode: str  # "browser" | "locust" — determines publish target
    result: str  # summary string written by perf_test_streamer


class FinAnalysisState(TypedDict):
    """Typed state passed between all graph nodes.

    Fields are populated incrementally as each node runs.
    """

    query: str
    thread_id: str           # Correlation ID for logging / checkpointing
    ticker: str              # Resolved ticker symbol (set by query_optimizer)
    ticker_indexes: list[str]        # Major stock index tickers the ticker belongs to (set by query_optimizer)
    peer_tickers: list[str]      # Peer tickers for comparative data (set by query_optimizer)
    market_data_input: dict      # Structured {query, quants, news} output from query_optimizer
    market_data_output: dict     # Serialised MarketDataOutput from market_data_collector
    market_data: str
    fundamental_analysis: str
    technical_analysis: str
    risk_assessment: str
    report: str
    # Accumulate step-by-step logs so every node's I/O is traceable.
    steps: Annotated[list[str], _merge_lists]


class UnifiedGraphState(TypedDict):
    """Merged state for the unified parent graph that routes to either the
    financial analysis pipeline or the perf-test node.

    All fields from both :class:`FinAnalysisState` and :class:`PerfTestState`
    are present so the routing node and all downstream nodes can read from a
    single consistent dict.  Fields irrelevant to the active branch are
    populated with empty/zero defaults in the initial state set by the
    Celery runner and are simply ignored by the nodes that don't need them.
    """

    # --- shared ---
    thread_id: str
    query: str
    steps: Annotated[list[str], _merge_lists]

    # --- fin analysis fields ---
    ticker: str
    ticker_indexes: list[str]
    peer_tickers: list[str]
    market_data_input: dict
    market_data_output: dict
    market_data: str
    fundamental_analysis: str
    technical_analysis: str
    risk_assessment: str
    report: str

    # --- perf test fields (optional; perf_test_streamer uses its own defaults) ---
    total_tokens: NotRequired[int]
    timeout_secs: NotRequired[int]
    pub_mode: NotRequired[str]  # "browser" | "locust"
    result: NotRequired[str]
