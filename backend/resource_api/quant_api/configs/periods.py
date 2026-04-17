"""OHLCV window and period configuration."""

from __future__ import annotations

from dataclasses import dataclass

# Maps yfinance-style period strings to the equivalent number of calendar days.
# Used by providers when converting a period label to a concrete date range.
PERIOD_DAYS: dict[str, int] = {
    "1d":  1,
    "5d":  5,
    "1mo": 30,
    "3mo": 90,
    "6mo": 180,
    "1y":  365,
    "2y":  730,
    "5y":  1825,
    "10y": 3650,
    "max": 7300,
}


@dataclass(frozen=True)
class OhlcvWindow:
    """Configuration for a single OHLCV fetch window."""

    granularity: str      # quant_stats CHECK-constrained value, e.g. '15min'
    interval: str         # storage interval passed to upsert, e.g. '15m'
    fetch_interval: str   # interval requested from provider (may differ for resampled windows)
    period: str           # yfinance period string for a full (no-cache) fetch
    window_days: int      # how far back the window extends from now
    fresh_hours: float    # staleness threshold — skip fetch if latest bar is fresher


# Four canonical OHLCV windows used by market_data_collector.
# Source preference is resolved at fetch time via region-aware QuantClient
# (source="auto"), so no preferred_source column is needed here.
OHLCV_WINDOWS: list[OhlcvWindow] = [
    OhlcvWindow("15min", "15m", "15m",  "5d",  7,    0.5),
    OhlcvWindow("1h",    "1h",  "1h",   "1mo", 30,   2.0),
    OhlcvWindow("1day",  "1d",  "1d",   "2y",  730,  96.0),
    OhlcvWindow("1mo",   "1mo", "1mo",  "10y", 3650, 720.0),
]

# Window used for non-query tickers (peers, benchmark indexes, macro) — 2-year
# daily bars gives enough history for correlation / relative-strength analysis.
AUX_DAILY_WINDOW: OhlcvWindow = OhlcvWindow("1day", "1d", "1d", "2y", 730, 96.0)
