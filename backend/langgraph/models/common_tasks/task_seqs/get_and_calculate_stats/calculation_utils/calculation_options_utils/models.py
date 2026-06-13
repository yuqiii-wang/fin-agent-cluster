"""models -- Pydantic models for options stats calculation.

Contains all input/output models used by the calculate_option_stats task.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.quant.field_name_conversion import normalize_keys
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculation_options_utils.parser_utils import (
    extract_value,
    parse_numeric_value,
    parse_percent_value,
)


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

    @field_validator('contract_name', mode='before')
    @classmethod
    def _extract_contract_name(cls, v: Any) -> str | None:
        """Extract contract name from markdown links using parser_utils."""
        extracted = extract_value(v)
        if extracted is None:
            return None
        return str(extracted)

    @field_validator('strike', 'bid', 'ask', 'last', 'last_price', 'price_change', 'volume', 'open_interest', mode='before')
    @classmethod
    def _parse_numeric(cls, v: Any) -> float | None:
        """Parse numeric fields using parser_utils."""
        return parse_numeric_value(v)

    @field_validator('implied_volatility', 'pct_change', mode='before')
    @classmethod
    def _parse_percent(cls, v: Any) -> float | None:
        """Parse percentage fields using parser_utils."""
        return parse_percent_value(v)


class OptionContent(BaseModel):
    """Options content containing calls and puts lists."""
    model_config = ConfigDict(extra="ignore")
    
    calls: list[OptionContractInput] = Field(default_factory=list)
    puts: list[OptionContractInput] = Field(default_factory=list)


class StatsRecord(BaseModel):
    """Stats record containing symbol and options content."""
    model_config = ConfigDict(extra="ignore")
    
    id: str | None = None
    period: str | None = None
    symbol: str
    content: OptionContent


class CalculateOptionStatsInput(BaseModel):
    """Input for the calculate_option_stats handler.

    Supports two input formats:
    1. Nested format (from Celery worker):
       { "pipeline": "options", "from_cache": true, "stats_record": { "symbol": "...", "content": { "calls": [...], "puts": [...] } } }
    2. Flat format (from LangGraph):
       { "symbol": "...", "options": [...] }

    Attributes:
        pipeline:     Pipeline label (optional; used for routing). Always
                      ``'options'`` here, but this is inferred from the
                      presence of ``calls``/``puts`` rather than required.
        from_cache:   Whether data came from cache (optional).
        stats_record: Nested record containing symbol and options data (optional).
        symbol:       Underlying ticker symbol (used when stats_record is not provided).
        source:       Data source label persisted with every row, e.g. ``'web_content'``.
        options:      Flat list of all call and put contracts (used when stats_record is not provided).
    """

    model_config = ConfigDict(extra="ignore")

    pipeline: str | None = None
    from_cache: bool | None = None
    stats_record: StatsRecord | None = None
    symbol: str = ""
    source: str = "web_content"
    options: list[OptionContractInput] = Field(default_factory=list)

    @field_validator('stats_record', mode='before')
    @classmethod
    def _normalize_stats_record(cls, v: Any) -> Any:
        """Normalize field names in the stats_record before validation."""
        if v is None:
            return v
        if isinstance(v, dict):
            v = normalize_keys(v)
            if 'content' in v and isinstance(v['content'], dict):
                v['content'] = normalize_keys(v['content'])
                # Normalize keys in calls and puts lists
                for key in ['calls', 'puts']:
                    if key in v['content'] and isinstance(v['content'][key], list):
                        v['content'][key] = [cls._normalize_contract(item) if isinstance(item, dict) else item 
                                            for item in v['content'][key]]
        return v

    @field_validator('options', mode='before')
    @classmethod
    def _normalize_options(cls, v: Any) -> Any:
        """Normalize field names in the options list before validation."""
        if v is None:
            return []
        if isinstance(v, list):
            return [cls._normalize_contract(item) if isinstance(item, dict) else item 
                    for item in v]
        return v

    @staticmethod
    def _normalize_contract(item: dict) -> dict:
        """Normalize contract dictionary keys, handling special cases."""
        # Normalize keys to snake_case
        item = normalize_keys(item)
        
        # Handle special cases that normalize_keys doesn't handle correctly
        if '%_change' in item:
            item['pct_change'] = item.pop('%_change')
        if 'last_price' not in item and 'last' in item:
            item['last_price'] = item['last']
        
        return item

    @property
    def resolved_symbol(self) -> str:
        """Return the symbol, preferring the one from stats_record if available."""
        if self.stats_record:
            return self.stats_record.symbol
        return self.symbol

    @property
    def resolved_options(self) -> list[OptionContractInput]:
        """Return combined list of all call and put contracts."""
        if self.stats_record:
            return self.stats_record.content.calls + self.stats_record.content.puts
        return self.options


class VolSmilePoint(BaseModel):
    """A single (strike, implied_volatility, cost, volume) data point for call and/or put at that strike.

    The volatility smile plots implied volatility against strike price, showing the
    characteristic "smile" pattern where IV is higher for deep ITM and OTM options.

    Attributes:
        strike:       Strike price.
        call_iv:      Call implied volatility at this strike (percent, e.g. 107.81), or None.
        put_iv:       Put implied volatility at this strike (percent), or None.
        call_cost:    Call option cost/premium (mid-price from bid/ask or last), or None.
        put_cost:     Put option cost/premium (mid-price from bid/ask or last), or None.
        call_volume:  Call option trading volume (number of contracts), or None.
        put_volume:   Put option trading volume (number of contracts), or None.
    """

    strike: float
    call_iv: float | None = None
    put_iv: float | None = None
    call_cost: float | None = None
    put_cost: float | None = None
    call_volume: float | None = None
    put_volume: float | None = None


class VolSmileExpiry(BaseModel):
    """Per-expiry volatility smile and volume -- strike/IV/volume points for one expiry date.

    The volatility smile shows implied volatility across strike prices, while the
    accompanying volume bar chart displays trading activity at each strike.

    Attributes:
        expiry_date: Contract maturity as ISO date string, e.g. ``'2026-06-01'``.
        points:      Strike/IV/volume pairs sorted ascending by strike price.
    """

    expiry_date: str
    points: list[VolSmilePoint]


from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.models import CalculateStatsBaseOutput

class CalculateOptionStatsOutput(CalculateStatsBaseOutput):
    """Output from the calculate_option_stats handler.

    The volatility smile visualization displays two key metrics for each strike price:
    1. Implied Volatility (IV %): The market's expectation of future volatility
    2. Option Cost/Premium: The actual price to buy the option contract

    For each expiry date, the smile shows:
    - Call options (dashed blue line): IV and cost for right-to-buy contracts
    - Put options (solid orange line): IV and cost for right-to-sell contracts

    Attributes:
        rows_upserted:       Total rows upserted (contracts_upserted + expiries_aggregated).
        symbol:              Underlying ticker symbol.
        source:              Data source label.
        contracts_upserted:  Per-contract rows written to ``quant_options_stats``.
        contracts_skipped:   Contracts skipped because ``contract_name`` failed to parse.
        expiries_aggregated: Aggregate rows written to ``quant_derivative_stats``.
        expiries_skipped:    Expiries skipped because calls and puts shared no strike.
        stats_views:         Frontend view type list; always ``["VolatilitySmile"]``.
        vol_smile:           Per-expiry volatility smile data with IV and cost for calls/puts.
    """

    contracts_upserted: int
    contracts_skipped: int
    expiries_aggregated: int
    expiries_skipped: int
    stats_views: list[str] = Field(default_factory=lambda: ["VolatilitySmile"])
    vol_smile: list[VolSmileExpiry] = Field(default_factory=list)


__all__ = [
    "OptionContractInput",
    "OptionContent",
    "StatsRecord",
    "CalculateOptionStatsInput",
    "VolSmilePoint",
    "VolSmileExpiry",
    "CalculateOptionStatsOutput",
]
