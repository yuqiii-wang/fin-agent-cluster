"""Shared state schema for the financial analysis LangGraph workflow."""

from __future__ import annotations

from typing import Annotated, TypedDict


def _merge_lists(a: list[str], b: list[str]) -> list[str]:
    """Reducer that concatenates two step-log lists across parallel branches."""
    return a + b


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
