"""Output model for prepare_futures node."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["PrepareFuturesOutput", "FuturesInstrumentResult"]


class FuturesInstrumentResult(BaseModel):
    """Stats result for a single futures instrument.

    Attributes:
        code:          Short identifier, e.g. ``'gold'``.
        symbol:        Provider ticker, e.g. ``'GC=F'``.
        label:         Human-readable name, e.g. ``'Gold'``.
        currency_code: ISO 4217 code, e.g. ``'USD'``.
        rows_upserted: Number of bar rows written to the stats table.
        granularity:   Bar granularity stored (e.g. ``'1day'``).
        source:        Provider source label (e.g. ``'yfinance'``).
        from_cache:    Whether the raw stats were served from cache.
    """

    code: str = Field(description="Short identifier, e.g. 'gold'.")
    symbol: str = Field(description="Provider ticker, e.g. 'GC=F'.")
    label: str = Field(description="Human-readable name.")
    currency_code: str | None = Field(default=None, description="ISO 4217 currency code.")
    rows_upserted: int = Field(default=0, description="Bar rows written to stats table.")
    granularity: str = Field(default="", description="Bar granularity stored.")
    source: str = Field(default="", description="Provider source label.")
    from_cache: bool = Field(default=False, description="Whether raw stats were cache-served.")


class PrepareFuturesOutput(BaseModel):
    """Typed output for ``prepare_futures``.

    Persisted to ``fin_agents.node_executions`` for downstream nodes / rendering.

    Attributes:
        instruments: Per-instrument stats results for the configured futures universe.
        period:      Stats aggregation period used.
        df_splits:   Per-symbol OHLCV df_split payloads for StackCandleStick rendering.
    """

    instruments: list[FuturesInstrumentResult] = Field(
        default_factory=list,
        description="Per-instrument stats results for the configured futures universe.",
    )
    period: str = Field(default="1y", description="Stats aggregation period used.")
    df_splits: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Per-symbol OHLCV df_split payloads for StackCandleStick rendering.",
    )
