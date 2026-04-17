"""yfinance provider for quant market data."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import yfinance as yf

from backend.resource_api.exceptions import ProviderNotFoundError
from backend.resource_api.quant_api.models import (
    OHLCVBar,
    PriceQuote,
    QuantQuery,
    QuantResult,
)

# yfinance period strings accepted by Ticker.history()
_VALID_PERIODS = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}
_VALID_INTRADAY_INTERVALS = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h"}
_VALID_INTERVALS = _VALID_INTRADAY_INTERVALS | {"1d", "1wk", "1mo"}

from backend.resource_api.quant_api.configs.ticker_maps.yfinance import TICKER_MAP  # noqa: F401


def _fetch_daily_ohlcv(symbol: str, params: dict[str, Any]) -> QuantResult:
    """Fetch daily OHLCV bars from yfinance (blocking, runs in thread)."""
    period = params.get("period", "3mo")
    if period not in _VALID_PERIODS:
        period = "3mo"
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval="1d", auto_adjust=True)
    if df.empty:
        raise ProviderNotFoundError("yfinance", "Ticker.history(1d)", symbol, f"empty DataFrame for period={period}")
    bars = [
        OHLCVBar(
            date=str(row.Index.date()),
            open=round(float(row.Open), 6),
            high=round(float(row.High), 6),
            low=round(float(row.Low), 6),
            close=round(float(row.Close), 6),
            volume=int(row.Volume),
        )
        for row in df.itertuples()
    ]
    return QuantResult(
        symbol=symbol.upper(),
        method="daily_ohlcv",
        source="yfinance",
        bars=bars,
        fetched_at=datetime.now(timezone.utc),
    )


def _fetch_intraday_ohlcv(symbol: str, params: dict[str, Any]) -> QuantResult:
    """Fetch intraday OHLCV bars from yfinance (blocking, runs in thread)."""
    interval = params.get("interval", "5m")
    if interval not in _VALID_INTRADAY_INTERVALS:
        interval = "5m"
    period = params.get("period", "1d")
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=interval, auto_adjust=True)
    if df.empty:
        raise ProviderNotFoundError("yfinance", f"Ticker.history({interval})", symbol, f"empty DataFrame for period={period}")
    bars = [
        OHLCVBar(
            date=row.Index.isoformat(),
            open=round(float(row.Open), 6),
            high=round(float(row.High), 6),
            low=round(float(row.Low), 6),
            close=round(float(row.Close), 6),
            volume=int(row.Volume),
        )
        for row in df.itertuples()
    ]
    return QuantResult(
        symbol=symbol.upper(),
        method="intraday_ohlcv",
        source="yfinance",
        bars=bars,
        fetched_at=datetime.now(timezone.utc),
    )


def _fetch_quote(symbol: str) -> QuantResult:
    """Fetch current price quote from yfinance (blocking, runs in thread)."""
    ticker = yf.Ticker(symbol)
    info = ticker.info
    price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("ask") or 0.0
    if not price:
        raise ProviderNotFoundError("yfinance", "Ticker.info (quote)", symbol, "price=0 / no market info")
    prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
    change = round(price - prev_close, 4) if prev_close else None
    change_pct = round(change / prev_close * 100, 4) if prev_close and change is not None else None
    quote = PriceQuote(
        symbol=symbol.upper(),
        price=float(price),
        change=change,
        change_pct=change_pct,
        volume=info.get("volume") or info.get("regularMarketVolume"),
        market_cap=info.get("marketCap"),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    return QuantResult(
        symbol=symbol.upper(),
        method="quote",
        source="yfinance",
        quote=quote,
        fetched_at=datetime.now(timezone.utc),
    )


def _fetch_overview(symbol: str) -> QuantResult:
    """Fetch company overview / fundamentals from yfinance (blocking, runs in thread)."""
    ticker = yf.Ticker(symbol)
    info = ticker.info
    # Keep a curated subset of commonly useful fields
    keep_keys = {
        "longName", "sector", "industry", "country", "fullTimeEmployees",
        "exchange", "fullExchangeName", "quoteType", "market",
        "marketCap", "enterpriseValue", "trailingPE", "forwardPE",
        "priceToBook", "trailingEps", "forwardEps", "dividendYield",
        "beta", "52WeekChange", "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
        "revenueGrowth", "earningsGrowth", "returnOnEquity", "debtToEquity",
        "freeCashflow", "operatingCashflow", "totalRevenue", "grossMargins",
        "operatingMargins", "profitMargins", "longBusinessSummary",
    }
    overview = {k: v for k, v in info.items() if k in keep_keys}
    return QuantResult(
        symbol=symbol.upper(),
        method="overview",
        source="yfinance",
        overview=overview,
        fetched_at=datetime.now(timezone.utc),
    )


def _fetch_periodic_ohlcv(symbol: str, params: dict[str, Any]) -> QuantResult:
    """Fetch OHLCV bars for any supported interval using period or start/end (blocking).

    Args:
        symbol: Ticker symbol (e.g. ``'AAPL'``).
        params: Accepted keys:
            - ``interval``: yfinance interval string (e.g. ``'15m'``, ``'1h'``, ``'1d'``, ``'1mo'``).
            - ``period``: yfinance period string (e.g. ``'5d'``, ``'1y'``); used when
              ``start`` is not provided.
            - ``start``: ISO-8601 datetime string; triggers date-range mode.
            - ``end``: ISO-8601 datetime string; defaults to now when ``start`` is given.
    """
    interval = params.get("interval", "1d")
    if interval not in _VALID_INTERVALS:
        interval = "1d"

    ticker = yf.Ticker(symbol)
    start = params.get("start")
    if start:
        # yfinance 0.3.x requires date-only strings (YYYY-MM-DD); strip time/tz component
        start = start[:10] if len(start) > 10 else start
        end_raw = params.get("end") or datetime.now(timezone.utc).isoformat()
        end = end_raw[:10] if len(end_raw) > 10 else end_raw
        df = ticker.history(interval=interval, start=start, end=end, auto_adjust=True)
    else:
        period = params.get("period", "1y")
        if period not in _VALID_PERIODS:
            period = "1y"
        df = ticker.history(interval=interval, period=period, auto_adjust=True)

    if df.empty:
        raise ProviderNotFoundError("yfinance", f"Ticker.history({interval})", symbol, "empty DataFrame")
    bars = [
        OHLCVBar(
            date=row.Index.isoformat(),
            open=round(float(row.Open), 6),
            high=round(float(row.High), 6),
            low=round(float(row.Low), 6),
            close=round(float(row.Close), 6),
            volume=int(row.Volume),
        )
        for row in df.itertuples()
    ]
    return QuantResult(
        symbol=symbol.upper(),
        method="periodic_ohlcv",
        source="yfinance",
        bars=bars,
        fetched_at=datetime.now(timezone.utc),
    )


async def fetch(query: QuantQuery) -> QuantResult:
    """Async entry-point: dispatches to the correct yfinance fetch function in a thread pool."""
    sym = query.symbol.upper()
    if query.method == "daily_ohlcv":
        return await asyncio.to_thread(_fetch_daily_ohlcv, sym, query.params)
    if query.method == "intraday_ohlcv":
        return await asyncio.to_thread(_fetch_intraday_ohlcv, sym, query.params)
    if query.method == "periodic_ohlcv":
        return await asyncio.to_thread(_fetch_periodic_ohlcv, sym, query.params)
    if query.method == "quote":
        return await asyncio.to_thread(_fetch_quote, sym)
    if query.method == "overview":
        return await asyncio.to_thread(_fetch_overview, sym)
    raise ValueError(f"Unsupported method for yfinance provider: {query.method}")
