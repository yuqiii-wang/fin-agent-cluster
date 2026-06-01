"""Output model for prepare_index node."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.quant.stats import STATS_VIEW_TYPE

__all__ = ["AnalyzeIndexOutput", "IndexInstrumentResult", "IndexEquityResult"]


class IndexInstrumentResult(BaseModel):
    """Stats result for a single macro market-index instrument (e.g. SOFR 3-Month).

    Attributes:
        code:          Short identifier, e.g. ``'sofr_3m'``.
        symbol:        Provider ticker, e.g. ``'SR3=F'``.
        label:         Human-readable name, e.g. ``'SOFR 3-Month Futures'``.
        region:        Region code this index applies to, e.g. ``'us'``.  ``None`` for global.
        rows_upserted: Number of bar rows written to ``quant_stats``.
        granularity:   Bar granularity stored (e.g. ``'1day'``).
        source:        Provider source label (e.g. ``'yfinance'``).
        from_cache:    Whether the raw stats were served from cache.
    """

    code: str = Field(description="Short identifier, e.g. 'sofr_3m'.")
    symbol: str = Field(description="Provider ticker, e.g. 'SR3=F'.")
    label: str = Field(description="Human-readable name.")
    region: str | None = Field(default=None, description="Region code, e.g. 'us'.")
    rows_upserted: int = Field(description="Bar rows written to quant_stats.")
    granularity: str = Field(description="Bar granularity, e.g. '1day'.")
    source: str = Field(description="Provider source label.")
    from_cache: bool = Field(default=False, description="Whether raw stats were cache-served.")


class IndexEquityResult(BaseModel):
    """Stats result for a single equity benchmark index (e.g. S&P 500, Nikkei 225).

    Attributes:
        code:          Short identifier, e.g. ``'SP500'``.
        ticker:        Yahoo Finance index ticker, e.g. ``'^GSPC'``.
        name:          Human-readable name, e.g. ``'S&P 500'``.
        zone:          Geographic zone: ``'amer'``, ``'emea'``, or ``'apac'``.
        rows_upserted: Number of bar rows written to ``quant_stats``.
        granularity:   Bar granularity stored (e.g. ``'1day'``).
        source:        Provider source label (e.g. ``'fmp'``).
        from_cache:    Whether the raw stats were served from cache.
        is_added:      True when this index was added because the stock's home index
                       was not covered by the default set.
    """

    code: str = Field(description="Short identifier, e.g. 'SP500'.")
    ticker: str = Field(description="Yahoo Finance index ticker, e.g. '^GSPC'.")
    name: str = Field(description="Human-readable name, e.g. 'S&P 500'.")
    zone: str = Field(description="Geographic zone: 'amer', 'emea', or 'apac'.")
    rows_upserted: int = Field(description="Bar rows written to quant_stats.")
    granularity: str = Field(description="Bar granularity, e.g. '1day'.")
    source: str = Field(description="Provider source label.")
    from_cache: bool = Field(default=False, description="Whether raw stats were cache-served.")
    is_added: bool = Field(
        default=False,
        description="True when added as the stock's home index outside the default set.",
    )


class AnalyzeIndexOutput(BaseModel):
    """Typed output for ``prepare_index``.

    Persisted to ``fin_agents.node_executions`` for downstream nodes.

    Attributes:
        instruments:    Stats results for macro market-index instruments (e.g. SOFR 3-Month).
        equity_indexes: Stats results for equity benchmark indexes (SP500, NASDAQ 100, …).
        period:         Stats aggregation period used for all instruments.
        df_splits:      Per-symbol OHLCV df_split payloads for StackCandleStick rendering.
                        Shape: [{"symbol": str, "label": str, "df_split": DfSplitDict}, ...].
                        Equity indexes appear first, macro instruments after.
        stats_views:    Node-level stats view types; always ``["StackCandleStick"]``.
    """

    instruments: list[IndexInstrumentResult] = Field(
        default_factory=list,
        description="Stats results for each macro market-index instrument.",
    )
    equity_indexes: list[IndexEquityResult] = Field(
        default_factory=list,
        description="Stats results for each equity benchmark index.",
    )
    period: str = Field(description="Stats aggregation period used.")
    df_splits: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Per-symbol OHLCV df_splits for StackCandleStick rendering.",
    )
    stats_views: list[str] = Field(
        default_factory=lambda: [STATS_VIEW_TYPE.STACK_CANDLE_STICK.value],
        description="Node-level stats view types.",
    )
