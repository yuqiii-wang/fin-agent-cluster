"""Default provider ordering per market region.

The QuantClient uses these when no QUANT_SOURCES_* env override is present.
Keys are fin_markets.regions codes (lower-case) plus "default" and "macro".

Provider priority rules:
  - FMP is the primary provider for US equities (free tier, 250 calls/day).
  - yfinance is always last resort (free tier but unreliable for some symbols).
  - FRED is preferred for interest-rate and macro reference-price series.
  - datareader (Stooq) is preferred for commodity futures OHLCV.
  - akshare/alpha_vantage are preferred for Chinese A-share tickers.
"""

QUANT_SOURCE_DEFAULTS: dict[str, list[str]] = {
    "cn":      ["akshare", "alpha_vantage", "datareader", "yfinance"],
    "hk":      ["akshare", "alpha_vantage", "datareader", "yfinance"],
    "us":      ["fmp", "alpha_vantage", "datareader", "yfinance"],
    "au":      ["datareader", "yfinance"],
    # Macro chain: Stooq for metals/oil futures, FRED for rate/yield series,
    # yfinance as last resort for anything not covered above.
    "macro":   ["datareader", "fred", "yfinance"],
    "default": ["datareader", "yfinance"],
}
