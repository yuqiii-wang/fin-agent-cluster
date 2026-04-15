"""Pydantic models for the unified quant market-data API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

QuantMethod = Literal["daily_ohlcv", "intraday_ohlcv", "periodic_ohlcv", "quote", "overview"]
QuantSource = Literal["yfinance", "alpha_vantage", "akshare", "datareader", "auto"]


class QuantQuery(BaseModel):
    """Input specification for a quant market-data fetch."""

    symbol: str = Field(..., description="Ticker symbol, e.g. 'AAPL'")
    method: QuantMethod = Field(..., description="Data method to invoke")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Method-specific parameters. "
            "daily_ohlcv: {period?, outputsize?}; "
            "intraday_ohlcv: {interval, period?}; "
            "quote: {}; overview: {}"
        ),
    )
    thread_id: Optional[str] = Field(None, description="LangGraph thread id for traceability")
    node_name: str = Field("unknown", description="Graph node that issued this query")


class OHLCVBar(BaseModel):
    """Single OHLCV candlestick bar, normalised across all providers."""

    date: str = Field(..., description="ISO-8601 date or datetime string")
    open: float
    high: float
    low: float
    close: float
    volume: int
    adj_close: Optional[float] = None


class PriceQuote(BaseModel):
    """Current best-bid/ask snapshot, normalised across all providers."""

    symbol: str
    price: float
    change: Optional[float] = None
    change_pct: Optional[float] = None
    volume: Optional[int] = None
    market_cap: Optional[float] = None
    timestamp: str = Field(..., description="ISO-8601 datetime of the quote")


class QuantResult(BaseModel):
    """Unified output from any quant data provider."""

    symbol: str
    method: QuantMethod
    source: QuantSource
    bars: Optional[list[OHLCVBar]] = Field(None, description="Populated for *_ohlcv methods")
    quote: Optional[PriceQuote] = Field(None, description="Populated for quote method")
    overview: Optional[dict[str, Any]] = Field(None, description="Populated for overview method")
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    not_found_attempts: list[str] = Field(
        default_factory=list,
        description="Non-empty when all providers returned not-found; each entry describes an attempted provider.",
    )
