"""Alpha Vantage provider for quant market data."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from backend.resource_api.exceptions import ProviderNotFoundError
from backend.resource_api.quant_api.models import (
    OHLCVBar,
    PriceQuote,
    QuantQuery,
    QuantResult,
)

_BASE_URL = "https://www.alphavantage.co/query"

from backend.resource_api.quant_api.configs.ticker_maps.alpha_vantage import TICKER_MAP  # noqa: F401


async def _get(params: dict[str, Any], api_key: str, symbol: str, service: str) -> dict[str, Any]:
    """Make a GET request to the Alpha Vantage API.

    Args:
        params:  Query parameters (excluding apikey, which is appended here).
        api_key: Alpha Vantage API key.
        symbol:  Ticker symbol — used in ``ProviderNotFoundError`` messages.
        service: AV function name, e.g. ``"TIME_SERIES_DAILY"`` — used in errors.

    Raises:
        ProviderNotFoundError: On HTTP 404 or when AV returns an error message
            indicating the symbol was not found.
    """
    params = {**params, "apikey": api_key}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(_BASE_URL, params=params)
    if resp.status_code == 404:
        raise ProviderNotFoundError("alpha_vantage", service, symbol, f"HTTP 404 Not Found")
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    # AV returns HTTP 200 even for invalid symbols — check for error payloads
    if "Error Message" in data:
        raise ProviderNotFoundError("alpha_vantage", service, symbol, data["Error Message"])
    if "Information" in data and "premium" not in data["Information"].lower():
        # "Invalid API call" type messages (not rate-limit notices)
        raise ProviderNotFoundError("alpha_vantage", service, symbol, data["Information"])
    return data


async def _fetch_daily_ohlcv(symbol: str, params: dict[str, Any], api_key: str) -> QuantResult:
    """Fetch daily OHLCV bars from Alpha Vantage TIME_SERIES_DAILY."""
    outputsize = params.get("outputsize", "compact")  # 'compact' (100 days) or 'full'
    data = await _get(
        {"function": "TIME_SERIES_DAILY", "symbol": symbol, "outputsize": outputsize},
        api_key, symbol, "TIME_SERIES_DAILY",
    )
    ts = data.get("Time Series (Daily)", {})
    if not ts:
        raise ProviderNotFoundError("alpha_vantage", "TIME_SERIES_DAILY", symbol, "empty time series")
    bars = [
        OHLCVBar(
            date=date_str,
            open=float(v["1. open"]),
            high=float(v["2. high"]),
            low=float(v["3. low"]),
            close=float(v["4. close"]),
            volume=int(v["5. volume"]),
        )
        for date_str, v in sorted(ts.items())
    ]
    return QuantResult(
        symbol=symbol.upper(),
        method="daily_ohlcv",
        source="alpha_vantage",
        bars=bars,
        fetched_at=datetime.now(timezone.utc),
    )


async def _fetch_intraday_ohlcv(symbol: str, params: dict[str, Any], api_key: str) -> QuantResult:
    """Fetch intraday OHLCV bars from Alpha Vantage TIME_SERIES_INTRADAY."""
    interval = params.get("interval", "5min")
    # Normalise yfinance-style intervals ('5m') to AV style ('5min')
    if not interval.endswith("min") and interval.endswith("m"):
        interval = interval.replace("m", "min")
    outputsize = params.get("outputsize", "compact")
    data = await _get(
        {
            "function": "TIME_SERIES_INTRADAY",
            "symbol": symbol,
            "interval": interval,
            "outputsize": outputsize,
        },
        api_key, symbol, f"TIME_SERIES_INTRADAY/{interval}",
    )
    key = f"Time Series ({interval})"
    ts = data.get(key, {})
    if not ts:
        raise ProviderNotFoundError("alpha_vantage", f"TIME_SERIES_INTRADAY/{interval}", symbol, "empty time series")
    bars = [
        OHLCVBar(
            date=dt_str,
            open=float(v["1. open"]),
            high=float(v["2. high"]),
            low=float(v["3. low"]),
            close=float(v["4. close"]),
            volume=int(v["5. volume"]),
        )
        for dt_str, v in sorted(ts.items())
    ]
    return QuantResult(
        symbol=symbol.upper(),
        method="intraday_ohlcv",
        source="alpha_vantage",
        bars=bars,
        fetched_at=datetime.now(timezone.utc),
    )


async def _fetch_quote(symbol: str, api_key: str) -> QuantResult:
    """Fetch current price quote from Alpha Vantage GLOBAL_QUOTE."""
    data = await _get({"function": "GLOBAL_QUOTE", "symbol": symbol}, api_key, symbol, "GLOBAL_QUOTE")
    gq = data.get("Global Quote", {})
    price = float(gq.get("05. price", 0))
    if not price:
        raise ProviderNotFoundError("alpha_vantage", "GLOBAL_QUOTE", symbol, "price=0 (symbol not found)")
    change = float(gq.get("09. change", 0))
    change_pct_raw = gq.get("10. change percent", "0%").replace("%", "")
    quote = PriceQuote(
        symbol=symbol.upper(),
        price=price,
        change=change,
        change_pct=float(change_pct_raw),
        volume=int(gq.get("06. volume", 0)) or None,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    return QuantResult(
        symbol=symbol.upper(),
        method="quote",
        source="alpha_vantage",
        quote=quote,
        fetched_at=datetime.now(timezone.utc),
    )


async def _fetch_overview(symbol: str, api_key: str) -> QuantResult:
    """Fetch company overview from Alpha Vantage OVERVIEW endpoint."""
    data = await _get({"function": "OVERVIEW", "symbol": symbol}, api_key, symbol, "OVERVIEW")
    if not data.get("Symbol"):
        raise ProviderNotFoundError("alpha_vantage", "OVERVIEW", symbol, "empty overview (symbol not found)")
    return QuantResult(
        symbol=symbol.upper(),
        method="overview",
        source="alpha_vantage",
        overview=data,
        fetched_at=datetime.now(timezone.utc),
    )


async def _fetch_periodic_ohlcv(symbol: str, params: dict[str, Any], api_key: str) -> QuantResult:
    """Fetch OHLCV bars for any supported interval from Alpha Vantage.

    Routes to TIME_SERIES_DAILY, TIME_SERIES_WEEKLY, TIME_SERIES_MONTHLY, or
    TIME_SERIES_INTRADAY based on the ``interval`` param.  Filters by
    ``start`` date when provided.  Uses ``outputsize=full`` for long periods.
    """
    interval = params.get("interval", "1d")
    period = params.get("period", "")
    # Use full outputsize for long-range windows or incremental start-based fetches
    outputsize = "full" if period in {"1y", "2y", "5y", "10y", "max", "ytd"} or params.get("start") else "compact"

    if interval == "1mo":
        data = await _get({"function": "TIME_SERIES_MONTHLY", "symbol": symbol}, api_key, symbol, "TIME_SERIES_MONTHLY")
        ts = data.get("Monthly Time Series", {})
        svc = "TIME_SERIES_MONTHLY"
    elif interval == "1wk":
        data = await _get({"function": "TIME_SERIES_WEEKLY", "symbol": symbol}, api_key, symbol, "TIME_SERIES_WEEKLY")
        ts = data.get("Weekly Time Series", {})
        svc = "TIME_SERIES_WEEKLY"
    elif interval == "1d":
        data = await _get({"function": "TIME_SERIES_DAILY", "symbol": symbol, "outputsize": outputsize}, api_key, symbol, "TIME_SERIES_DAILY")
        ts = data.get("Time Series (Daily)", {})
        svc = "TIME_SERIES_DAILY"
    else:
        # Intraday: map yfinance-style intervals to AV style
        _AV_INTRADAY_MAP: dict[str, str] = {
            "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
            "60m": "60min", "1h": "60min",
        }
        _valid_intraday = {"1min", "5min", "15min", "30min", "60min"}
        av_interval = _AV_INTRADAY_MAP.get(interval, interval if interval.endswith("min") else None)
        if not av_interval or av_interval not in _valid_intraday:
            raise ValueError(f"Unsupported intraday interval for Alpha Vantage: {interval!r}")
        svc = f"TIME_SERIES_INTRADAY/{av_interval}"
        data = await _get(
            {"function": "TIME_SERIES_INTRADAY", "symbol": symbol, "interval": av_interval, "outputsize": outputsize},
            api_key, symbol, svc,
        )
        ts = data.get(f"Time Series ({av_interval})", {})

    if not ts:
        raise ProviderNotFoundError("alpha_vantage", svc, symbol, "empty time series")

    start_filter = params.get("start", "")[:10] if params.get("start") else None
    bars = [
        OHLCVBar(
            date=date_str,
            open=float(v["1. open"]),
            high=float(v["2. high"]),
            low=float(v["3. low"]),
            close=float(v["4. close"]),
            volume=int(v.get("5. volume", 0)),
        )
        for date_str, v in sorted(ts.items())
        if not start_filter or date_str[:10] >= start_filter
    ]
    return QuantResult(
        symbol=symbol.upper(),
        method="periodic_ohlcv",
        source="alpha_vantage",
        bars=bars,
        fetched_at=datetime.now(timezone.utc),
    )


async def fetch(query: QuantQuery, api_key: str) -> QuantResult:
    """Async entry-point: dispatches to the correct Alpha Vantage fetch function."""
    sym = query.symbol.upper()
    if query.method == "daily_ohlcv":
        return await _fetch_daily_ohlcv(sym, query.params, api_key)
    if query.method == "intraday_ohlcv":
        return await _fetch_intraday_ohlcv(sym, query.params, api_key)
    if query.method == "periodic_ohlcv":
        return await _fetch_periodic_ohlcv(sym, query.params, api_key)
    if query.method == "quote":
        return await _fetch_quote(sym, api_key)
    if query.method == "overview":
        return await _fetch_overview(sym, api_key)
    raise ValueError(f"Unsupported method for alpha_vantage provider: {query.method}")
