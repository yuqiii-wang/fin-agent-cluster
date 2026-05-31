"""models — Pydantic models for options stats calculation.

Contains all input/output models used by the calculate_option_stats task.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class OptionContractInput(BaseModel):
    """A single call/put contract extracted from an options-chain page.

    Attributes:
        contract_name:      Full OSI option symbol, e.g. ``'AAPL260601P00250000'``.
        options_type:       ``'call'`` or ``'put'`` (informational; the authoritative
                            value is parsed from ``contract_name``).
        strike:             Strike price (informational; parsed from ``contract_name``).
        bid:                Bid price.
        ask:                Ask price.
        last:               Last traded price (page field name).
        last_price:         Last traded price (alternate field name); preferred over ``last``.
        last_trade_date:    Last trade timestamp (ISO-8601 string).
        price_change:       Absolute session price change.
        pct_change:         Percent session price change (``'1.23%'`` or ``1.23``).
        volume:             Session contract volume.
        open_interest:      Per-contract open interest.
        implied_volatility: Implied volatility (``'107.81%'`` or ``107.81``).
    """

    model_config = ConfigDict(extra="ignore")

    contract_name: str
    options_type: str | None = None
    strike: float | None = None
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    last_price: float | None = None
    last_trade_date: str | None = None
    price_change: float | None = None
    pct_change: float | str | None = None
    volume: float | None = None
    open_interest: float | None = None
    implied_volatility: float | str | None = None


class CalculateOptionStatsInput(BaseModel):
    """Input for the calculate_option_stats handler.

    Attributes:
        symbol:  Underlying ticker symbol, e.g. ``'AAPL'``.
        source:  Data source label persisted with every row, e.g. ``'web_content'``.
        options: Flat list of all call and put contracts extracted from the options chain.
    """

    symbol: str
    source: str = "web_content"
    options: list[OptionContractInput] = Field(default_factory=list)


class VolSmilePoint(BaseModel):
    """A single (strike, implied_volatility) pair for call and/or put at that strike.

    Attributes:
        strike:  Strike price.
        call_iv: Call implied volatility at this strike (percent, e.g. 107.81), or None.
        put_iv:  Put implied volatility at this strike (percent), or None.
    """

    strike: float
    call_iv: float | None = None
    put_iv: float | None = None


class VolSmileExpiry(BaseModel):
    """Per-expiry volatility smile — strike/IV points for one expiry date.

    Attributes:
        expiry_date: Contract maturity as ISO date string, e.g. ``'2026-06-01'``.
        points:      Strike/IV pairs sorted ascending by strike price.
    """

    expiry_date: str
    points: list[VolSmilePoint]


class CalculateOptionStatsOutput(BaseModel):
    """Output from the calculate_option_stats handler.

    Attributes:
        symbol:              Underlying ticker symbol.
        source:              Data source label.
        contracts_upserted:  Per-contract rows written to ``quant_options_stats``.
        contracts_skipped:   Contracts skipped because ``contract_name`` failed to parse.
        expiries_aggregated: Aggregate rows written to ``quant_derivative_stats``.
        expiries_skipped:    Expiries skipped because calls and puts shared no strike.
        stats_views:         Frontend view type list; always ``["VolatilitySmile"]``.
        vol_smile:           Per-expiry volatility smile data for frontend rendering.
    """

    symbol: str
    source: str
    contracts_upserted: int
    contracts_skipped: int
    expiries_aggregated: int
    expiries_skipped: int
    stats_views: list[str] = Field(default_factory=lambda: ["VolatilitySmile"])
    vol_smile: list[VolSmileExpiry] = Field(default_factory=list)


__all__ = [
    "OptionContractInput",
    "CalculateOptionStatsInput",
    "VolSmilePoint",
    "VolSmileExpiry",
    "CalculateOptionStatsOutput",
]
