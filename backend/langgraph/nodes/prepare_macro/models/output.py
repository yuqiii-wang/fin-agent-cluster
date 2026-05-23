"""Output model for analyze_economics node."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["AnalyzeEconomicsOutput", "EconomicsInstrumentResult"]


class EconomicsInstrumentResult(BaseModel):
    """Stats result for a single economics instrument.

    Attributes:
        code:          Short identifier, e.g. ``'gold'``.
        symbol:        Provider ticker, e.g. ``'GC=F'``.
        label:         Human-readable name, e.g. ``'Gold'``.
        rows_upserted: Number of bar rows written to ``quant_stats``.
        granularity:   Bar granularity stored (e.g. ``'1day'``).
        source:        Provider source label (e.g. ``'yfinance'``).
        from_cache:    Whether the raw stats were served from cache.
    """

    code: str = Field(description="Short identifier, e.g. 'gold'.")
    symbol: str = Field(description="Provider ticker, e.g. 'GC=F'.")
    label: str = Field(description="Human-readable name, e.g. 'Gold'.")
    rows_upserted: int = Field(description="Bar rows written to quant_stats.")
    granularity: str = Field(description="Bar granularity, e.g. '1day'.")
    source: str = Field(description="Provider source label.")
    from_cache: bool = Field(default=False, description="Whether raw stats were cache-served.")


class AnalyzeEconomicsOutput(BaseModel):
    """Typed output for ``analyze_economics``.

    Persisted to ``fin_agents.node_executions`` for downstream nodes.

    Attributes:
        instruments: Stats results for each economics instrument (gold, silver,
                     natural gas, crude oil).
        period:      Stats aggregation period used for all instruments.
        df_splits:   Per-instrument OHLCV df_split payloads for StackCandleStick rendering.
                     Shape: [{"symbol": str, "label": str, "df_split": DfSplitDict}, ...].
        stats_views: Node-level stats view types; always ``["StackCandleStick"]``.
    """

    instruments: list[EconomicsInstrumentResult] = Field(
        default_factory=list,
        description="Stats results for each economics instrument.",
    )
    period: str = Field(description="Stats aggregation period used.")
    df_splits: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Per-instrument OHLCV df_splits for StackCandleStick rendering.",
    )
    stats_views: list[str] = Field(
        default_factory=lambda: ["StackCandleStick"],
        description="Node-level stats view types.",
    )
