"""Output model for prepare_futures node."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["PrepareFuturesOutput", "FuturesInstrumentResult"]


class FuturesInstrumentResult(BaseModel):
    """Stats result for a single futures instrument.

    Attributes:
        code:          Short identifier, e.g. ``"AAPL"`` or ``"gold"``.
        symbol:        Ticker symbol.
        label:         Human-readable label.
        rows_upserted: Number of bar rows written to quant_*_stats.
        granularity:   Bar granularity, e.g. ``"1day"``.
        source:        Provider source label.
        from_cache:    ``True`` when raw stats were cache-served.
        pipeline:      ``"futures"`` (fixed, downstream grouping key).
        maturity_label: Short label for the maturity window if set.
        maturity_seconds: Raw seconds width of the maturity window if set.
    """

    code: str = Field(description="Short identifier.")
    symbol: str = Field(description="Ticker symbol.")
    label: str = Field(description="Human-readable label.")
    rows_upserted: int = Field(default=0, description="Bar rows written.")
    granularity: str = Field(default="", description="Bar granularity.")
    source: str = Field(default="", description="Provider source label.")
    from_cache: bool = Field(default=False, description="Whether raw stats were cache-served.")
    pipeline: str = Field(default="futures", description="Fixed to 'futures'.")
    maturity_label: str | None = Field(
        default=None,
        description="Short maturity-window label when maturity_horizon was configured.",
    )
    maturity_seconds: int | None = Field(
        default=None,
        description="Raw seconds width of the maturity window when maturity_horizon was configured.",
    )


class PrepareFuturesOutput(BaseModel):
    """Typed output for ``prepare_futures``.

    Attributes:
        instruments:    Per-symbol :class:`FuturesInstrumentResult` objects.
        futures_period: Period used by every fan-out call (``"1y"`` ...).
        stock_symbol:   Explicit stock_symbol provided by the caller, or
                        ``None`` when the macro_instruments catalogue was used.
        df_splits:      Per-symbol ``df_split`` payload for StackCandleStick rendering.
    """

    instruments: list[FuturesInstrumentResult] = Field(
        default_factory=list,
        description="Per-symbol futures-stats results.",
    )
    futures_period: str = Field(default="1y", description="Period used for the fan-out.")
    stock_symbol: str | None = Field(
        default=None,
        description="Explicit stock_symbol provided by the caller, or None when using the catalogue.",
    )
    df_splits: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Per-symbol df_split payloads for StackCandleStick rendering.",
    )
