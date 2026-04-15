"""Shared constants for the quant market-data API."""

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

# Default ordered provider lists per market region.
# The QuantClient uses these when no QUANT_SOURCES_* env override is present.
# Keys are fin_markets.regions codes (lower-case) plus "default".
QUANT_SOURCE_DEFAULTS: dict[str, list[str]] = {
    "cn":      ["akshare", "alpha_vantage", "yfinance"],
    "hk":      ["akshare", "alpha_vantage", "yfinance"],
    "us":      ["alpha_vantage", "datareader", "yfinance"],
    "au":      ["datareader", "yfinance"],
    "default": ["datareader", "yfinance"],
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

# ---------------------------------------------------------------------------
# Index label keyword → canonical ticker symbol
# Keys match the label-keyword values stored in fin_markets.regions.indexes
# (TEXT[] column; spaces replaced with '_' in SQL seed data).
# Used by the market_data node to resolve a human-readable label to the
# actual ticker that quant providers accept.
# ---------------------------------------------------------------------------
INDEX_LABEL_TICKER_MAP: dict[str, str] = {
    # ── United States ──────────────────────────────────────────────────────
    "NASDAQ_100":  "^NDX",
    "NASDAQ":      "^IXIC",
    "S&P_500":     "^GSPC",
    "DOW_JONES":   "^DJI",
    "RUSSELL":     "^RUT",
    # ── Canada ─────────────────────────────────────────────────────────────
    "S&P/TSX":     "^GSPTSE",
    # ── Brazil ─────────────────────────────────────────────────────────────
    "IBOVESPA":    "^BVSP",
    "BVSP":        "^BVSP",
    # ── Mexico ─────────────────────────────────────────────────────────────
    "IPC":         "^MXX",
    # ── United Kingdom ─────────────────────────────────────────────────────
    "FTSE":        "^FTSE",
    # ── Germany ────────────────────────────────────────────────────────────
    "DAX":         "^GDAXI",
    # ── France ─────────────────────────────────────────────────────────────
    "CAC":         "^FCHI",
    # ── Switzerland ────────────────────────────────────────────────────────
    "SMI":         "^SSMI",
    # ── Netherlands ────────────────────────────────────────────────────────
    "AEX":         "^AEX",
    # ── Sweden ─────────────────────────────────────────────────────────────
    "OMX":         "^OMX",
    # ── Norway ─────────────────────────────────────────────────────────────
    "OBX":         "^OBX",
    # ── Italy ──────────────────────────────────────────────────────────────
    "FTSE_MIB":    "FTSEMIB.MI",
    "MIB":         "FTSEMIB.MI",
    # ── Spain ──────────────────────────────────────────────────────────────
    "IBEX":        "^IBEX",
    # ── Saudi Arabia ───────────────────────────────────────────────────────
    "TADAWUL":     "^TASI.SR",
    "TASI":        "^TASI.SR",
    # ── Japan ──────────────────────────────────────────────────────────────
    "NIKKEI":      "^N225",
    "TOPIX":       "^TOPX",
    # ── China ──────────────────────────────────────────────────────────────
    "SHANGHAI":    "000001.SS",
    "CSI_300":     "000300.SS",
    "SSE":         "000001.SS",
    "000001":      "000001.SS",
    "SHENZHEN":    "399001.SZ",
    "399001":      "399001.SZ",
    # ── Hong Kong ──────────────────────────────────────────────────────────
    "HANG_SENG":   "^HSI",
    # ── Taiwan ─────────────────────────────────────────────────────────────
    "TAIEX":       "^TWII",
    # ── South Korea ────────────────────────────────────────────────────────
    "KOSPI":       "^KS11",
    # ── Singapore ──────────────────────────────────────────────────────────
    "STRAITS":     "^STI",
    "STI":         "^STI",
    # ── India ──────────────────────────────────────────────────────────────
    "SENSEX":      "^BSESN",
    "NIFTY":       "^NSEI",
    "BSE":         "^BSESN",
    # ── Australia ──────────────────────────────────────────────────────────
    "ASX_200":     "^AXJO",
    "ASX":         "^AXJO",
    # ── New Zealand ────────────────────────────────────────────────────────
    "NZX":         "^NZ50",
    # ── Indonesia ──────────────────────────────────────────────────────────
    "IDX":         "^JKSE",
    # ── Malaysia ───────────────────────────────────────────────────────────
    "BURSA":       "^KLSE",
    "KLCI":        "^KLSE",
    # ── Thailand ───────────────────────────────────────────────────────────
    "SET":         "^SET.BK",
}
