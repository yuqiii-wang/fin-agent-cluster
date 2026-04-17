"""FMP (Financial Modeling Prep) provider for quant market data.

Uses the FMP stable REST API:
  https://financialmodelingprep.com/stable

Supported endpoints:
  - ``/historical-price-eod/full``  — daily OHLCV bars (daily_ohlcv, periodic_ohlcv)
  - ``/quote``                       — real-time price quote (quote)
  - ``/profile``                     — company fundamentals (overview)

Intraday data is not available on FMP free tier; those requests fall through
to the next provider in the chain.

Free-tier limits: 250 API calls / day.  The 4-hour DB cache in QuantClient
reduces live calls significantly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from backend.resource_api.exceptions import ProviderNotFoundError
from backend.resource_api.quant_api.configs.periods import PERIOD_DAYS
from backend.resource_api.quant_api.configs.ticker_maps.fmp import TICKER_MAP  # noqa: F401
from backend.resource_api.quant_api.models import OHLCVBar, PriceQuote, QuantQuery, QuantResult

_PROVIDER = "fmp"


def _parse_date_range(params: dict[str, Any]) -> tuple[str, str]:
    """Derive start/end date strings from query params.

    Args:
        params: Query params (may contain 'period', 'start').

    Returns:
        Tuple of (start, end) as ``'YYYY-MM-DD'`` strings.
    """
    end_dt = datetime.now(timezone.utc)
    end_str = end_dt.strftime("%Y-%m-%d")

    if "start" in params:
        try:
            start_dt = datetime.fromisoformat(params["start"].replace("Z", "+00:00"))
            return start_dt.strftime("%Y-%m-%d"), end_str
        except (ValueError, AttributeError):
            pass

    period = params.get("period", "1y")
    days = PERIOD_DAYS.get(period, 365)
    start_str = (end_dt - timedelta(days=days)).strftime("%Y-%m-%d")
    return start_str, end_str


async def _get(base_url: str, path: str, params: dict[str, Any], api_key: str, symbol: str) -> Any:
    """Make a GET request to the FMP stable API.

    Args:
        base_url: FMP base URL (from settings).
        path:     API path relative to base URL, e.g. ``'/historical-price-eod/full'``.
        params:   Query parameters (excluding apikey, which is appended here).
        api_key:  FMP API key.
        symbol:   Ticker symbol — used in error messages.

    Returns:
        Parsed JSON response.

    Raises:
        ProviderNotFoundError: On HTTP 404 or empty/error JSON payload.
    """
    url = base_url.rstrip("/") + path
    all_params = {**params, "apikey": api_key}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, params=all_params)
    if resp.status_code == 404:
        raise ProviderNotFoundError(_PROVIDER, path, symbol, "HTTP 404 Not Found")
    resp.raise_for_status()
    data = resp.json()
    # FMP returns {"Error Message": "..."} on unknown symbol or invalid key
    if isinstance(data, dict) and "Error Message" in data:
        raise ProviderNotFoundError(_PROVIDER, path, symbol, data["Error Message"])
    return data


async def _fetch_daily_ohlcv(symbol: str, params: dict[str, Any], base_url: str, api_key: str) -> QuantResult:
    """Fetch daily OHLCV bars from FMP /historical-price-eod/full.

    Args:
        symbol:   FMP-translated ticker symbol.
        params:   Query params (period, start).
        base_url: FMP base URL from settings.
        api_key:  FMP API key.

    Returns:
        :class:`QuantResult` with ascending daily bars.

    Raises:
        ProviderNotFoundError: When the payload is empty or the symbol is unknown.
    """
    start, end = _parse_date_range(params)
    data = await _get(
        base_url,
        "/historical-price-eod/full",
        {"symbol": symbol, "from": start, "to": end},
        api_key,
        symbol,
    )
    historical: list[dict[str, Any]] = (
        data.get("historical", []) if isinstance(data, dict) else []
    )
    if not historical:
        raise ProviderNotFoundError(_PROVIDER, "/historical-price-eod/full", symbol, "empty historical data")
    bars = [
        OHLCVBar(
            date=row["date"],
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=int(row.get("volume") or 0),
            adj_close=float(row["adjClose"]) if row.get("adjClose") is not None else None,
        )
        for row in sorted(historical, key=lambda r: r["date"])
    ]
    return QuantResult(
        symbol=symbol.upper(),
        method="daily_ohlcv",
        source=_PROVIDER,
        bars=bars,
        fetched_at=datetime.now(timezone.utc),
    )


async def _fetch_periodic_ohlcv(symbol: str, params: dict[str, Any], base_url: str, api_key: str) -> QuantResult:
    """Fetch periodic OHLCV bars from FMP.

    FMP stable free tier only provides daily (EOD) data; intraday and weekly/monthly
    intervals are not supported.  Daily is served via ``/historical-price-eod/full``.

    Args:
        symbol:   FMP-translated ticker symbol.
        params:   Query params (period, start, interval).
        base_url: FMP base URL from settings.
        api_key:  FMP API key.

    Returns:
        :class:`QuantResult` with ascending daily bars.

    Raises:
        ProviderNotFoundError: When the interval is not daily or data is empty.
    """
    interval = params.get("interval", "1d")
    if interval not in {"1d", "daily"}:
        raise ProviderNotFoundError(
            _PROVIDER, "periodic_ohlcv", symbol,
            f"FMP free tier only supports daily interval; got {interval!r}",
        )
    result = await _fetch_daily_ohlcv(symbol, params, base_url, api_key)
    return result.model_copy(update={"method": "periodic_ohlcv"})


async def _fetch_quote(symbol: str, base_url: str, api_key: str) -> QuantResult:
    """Fetch a real-time price quote from FMP /quote.

    Args:
        symbol:   FMP-translated ticker symbol.
        base_url: FMP base URL from settings.
        api_key:  FMP API key.

    Returns:
        :class:`QuantResult` with a populated :class:`PriceQuote`.

    Raises:
        ProviderNotFoundError: When the payload is empty or price is zero.
    """
    data = await _get(base_url, "/quote", {"symbol": symbol}, api_key, symbol)
    rows: list[dict[str, Any]] = data if isinstance(data, list) else []
    if not rows:
        raise ProviderNotFoundError(_PROVIDER, "/quote", symbol, "empty quote response")
    row = rows[0]
    price = float(row.get("price") or 0)
    if not price:
        raise ProviderNotFoundError(_PROVIDER, "/quote", symbol, "price=0 (symbol not found or market closed)")
    quote = PriceQuote(
        symbol=symbol.upper(),
        price=price,
        change=float(row["change"]) if row.get("change") is not None else None,
        change_pct=float(row["changesPercentage"]) if row.get("changesPercentage") is not None else None,
        volume=int(row["volume"]) if row.get("volume") else None,
        market_cap=float(row["marketCap"]) if row.get("marketCap") else None,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    return QuantResult(
        symbol=symbol.upper(),
        method="quote",
        source=_PROVIDER,
        quote=quote,
        fetched_at=datetime.now(timezone.utc),
    )


async def _fetch_overview(symbol: str, base_url: str, api_key: str) -> QuantResult:
    """Fetch company profile / overview from FMP /profile.

    Args:
        symbol:   FMP-translated ticker symbol.
        base_url: FMP base URL from settings.
        api_key:  FMP API key.

    Returns:
        :class:`QuantResult` with a populated ``overview`` dict.

    Raises:
        ProviderNotFoundError: When the payload is empty or the symbol is unknown.
    """
    data = await _get(base_url, "/profile", {"symbol": symbol}, api_key, symbol)
    rows: list[dict[str, Any]] = data if isinstance(data, list) else []
    if not rows:
        raise ProviderNotFoundError(_PROVIDER, "/profile", symbol, "empty profile response")
    return QuantResult(
        symbol=symbol.upper(),
        method="overview",
        source=_PROVIDER,
        overview=rows[0],
        fetched_at=datetime.now(timezone.utc),
    )


async def fetch(query: QuantQuery, base_url: str, api_key: str) -> QuantResult:
    """Async entry-point: dispatches to the correct FMP fetch function.

    Args:
        query:    Structured market-data query.
        base_url: FMP base URL (from :attr:`~backend.config.Settings.FMP_BASE_URL`).
        api_key:  FMP API key (from :attr:`~backend.config.Settings.FMP_API_KEY`).

    Returns:
        Normalised :class:`QuantResult`.

    Raises:
        ProviderNotFoundError: When the symbol/method is unsupported.
        ValueError: When the method is unknown.
    """
    sym = query.symbol.upper()
    if query.method == "daily_ohlcv":
        return await _fetch_daily_ohlcv(sym, query.params, base_url, api_key)
    if query.method == "periodic_ohlcv":
        return await _fetch_periodic_ohlcv(sym, query.params, base_url, api_key)
    if query.method == "intraday_ohlcv":
        raise ProviderNotFoundError(_PROVIDER, "intraday_ohlcv", sym, "FMP free tier does not support intraday data")
    if query.method == "quote":
        return await _fetch_quote(sym, base_url, api_key)
    if query.method == "overview":
        return await _fetch_overview(sym, base_url, api_key)
    raise ValueError(f"Unsupported method for fmp provider: {query.method}")
