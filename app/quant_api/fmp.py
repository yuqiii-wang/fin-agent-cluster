"""Financial Modeling Prep (FMP) API client.

Docs: https://site.financialmodelingprep.com/developer/docs

Provides market data, fundamentals, news, and macro indicators
via the QuantAPIBase interface.
"""

from datetime import date
from typing import Any

import httpx

from app.quant_api.base import QuantAPIBase


class FMPClient(QuantAPIBase):
    """HTTP client for Financial Modeling Prep API v3/v4 and stable."""

    BASE_URL = "https://financialmodelingprep.com"

    def __init__(self, api_key: str, base_url: str | None = None, timeout: float = 30.0) -> None:
        """Initialize FMP client.

        Args:
            api_key: FMP API key.
            base_url: Optional base URL override (e.g. stable API URL from settings).
            timeout: HTTP request timeout in seconds.
        """
        self._api_key = api_key
        resolved_base = (base_url or self.BASE_URL).rstrip("/")
        # Detect stable API: base URL ends with /stable or contains /stable
        self._use_stable = "stable" in resolved_base
        # For stable API the base is the full stable URL; for v3 strip to root
        if self._use_stable:
            http_base = resolved_base
        else:
            # Normalise to root domain
            http_base = resolved_base.split("/api")[0] if "/api" in resolved_base else resolved_base
        self._client = httpx.AsyncClient(
            base_url=http_base,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    def _p(self, v3_path: str) -> str:
        """Translate a /api/v3 or /api/v4 path to /stable when using the stable API.

        Args:
            v3_path: Path starting with /api/v3/ or /api/v4/.

        Returns:
            Correct path for the configured API version.
        """
        if not self._use_stable:
            return v3_path
        # Strip /api/v3 or /api/v4 prefix and replace underscores with hyphens
        import re
        stable_path = re.sub(r"^/api/v[34]", "", v3_path)
        # Convert underscores in path segments to hyphens (FMP stable naming)
        stable_path = re.sub(r"_", "-", stable_path)
        return stable_path

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Make authenticated GET request to FMP API.

        Args:
            path: API endpoint path (e.g. '/api/v3/profile/AAPL').
            params: Additional query parameters.

        Returns:
            Parsed JSON response.

        Raises:
            httpx.HTTPStatusError: On 4xx/5xx responses.
        """
        params = params or {}
        params["apikey"] = self._api_key
        resp = await self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_company_profile(self, symbol: str) -> dict[str, Any]:
        """Fetch company profile for a symbol.

        FMP endpoints:
          - v3:     GET /api/v3/profile/{symbol}
          - stable: GET /stable/profile?symbol={symbol}
        """
        if self._use_stable:
            data = await self._get("/profile", {"symbol": symbol})
        else:
            data = await self._get(f"/api/v3/profile/{symbol}")
        return data[0] if isinstance(data, list) and data else {}

    async def get_historical_prices(
        self, symbol: str, from_date: date, to_date: date, interval: str = "1d"
    ) -> list[dict[str, Any]]:
        """Fetch historical OHLCV price bars.

        FMP endpoints:
          - v3 daily:     GET /api/v3/historical-price-full/{symbol}
          - stable daily: GET /stable/historical-price-eod/full?symbol={symbol}
          - v3 intraday:  GET /api/v3/historical-chart/{interval}/{symbol}
          - stable intra: GET /stable/historical-chart/{interval}?symbol={symbol}
        """
        date_params = {"from": from_date.isoformat(), "to": to_date.isoformat()}
        if interval == "1d":
            if self._use_stable:
                data = await self._get(
                    "/historical-price-eod/full",
                    {"symbol": symbol, **date_params},
                )
            else:
                data = await self._get(
                    f"/api/v3/historical-price-full/{symbol}", date_params
                )
            return data.get("historical", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        else:
            fmp_interval = _map_interval(interval)
            if self._use_stable:
                data = await self._get(
                    f"/historical-chart/{fmp_interval}",
                    {"symbol": symbol, **date_params},
                )
            else:
                data = await self._get(
                    f"/api/v3/historical-chart/{fmp_interval}/{symbol}", date_params
                )
            return data if isinstance(data, list) else []

    async def get_quote(self, symbol: str) -> dict[str, Any]:
        """Fetch real-time quote.

        FMP endpoints:
          - v3:     GET /api/v3/quote/{symbol}
          - stable: GET /stable/quote?symbol={symbol}
        """
        if self._use_stable:
            data = await self._get("/quote", {"symbol": symbol})
        else:
            data = await self._get(f"/api/v3/quote/{symbol}")
        return data[0] if isinstance(data, list) and data else {}

    async def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        """Fetch TTM key metrics.

        FMP endpoints:
          - v3:     GET /api/v3/key-metrics-ttm/{symbol}
          - stable: GET /stable/key-metrics-ttm?symbol={symbol}
        """
        if self._use_stable:
            data = await self._get("/key-metrics-ttm", {"symbol": symbol})
        else:
            data = await self._get(f"/api/v3/key-metrics-ttm/{symbol}")
        return data[0] if isinstance(data, list) and data else {}

    async def get_financial_ratios(self, symbol: str) -> dict[str, Any]:
        """Fetch TTM financial ratios.

        FMP endpoints:
          - v3:     GET /api/v3/ratios-ttm/{symbol}
          - stable: GET /stable/ratios-ttm?symbol={symbol}
        """
        if self._use_stable:
            data = await self._get("/ratios-ttm", {"symbol": symbol})
        else:
            data = await self._get(f"/api/v3/ratios-ttm/{symbol}")
        return data[0] if isinstance(data, list) and data else {}

    async def get_stock_news(
        self, symbol: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Fetch stock or market news.

        FMP endpoints:
          - v3:     GET /api/v3/stock_news?tickers={symbol}&limit={limit}
          - stable: GET /stable/stock-news?tickers={symbol}&limit={limit}
        """
        params: dict[str, Any] = {"limit": limit}
        if symbol:
            params["tickers"] = symbol
        path = "/stock-news" if self._use_stable else "/api/v3/stock_news"
        data = await self._get(path, params)
        return data if isinstance(data, list) else []

    async def get_index_constituents(self, index: str) -> list[dict[str, Any]]:
        """Fetch index constituents.

        FMP endpoints (v3):
          - S&P 500: GET /api/v3/sp500_constituent
          - NASDAQ:  GET /api/v3/nasdaq_constituent
          - Dow Jones: GET /api/v3/dowjones_constituent
        FMP endpoints (stable):
          - S&P 500: GET /stable/sp500-constituent
          - NASDAQ:  GET /stable/nasdaq-constituent
        """
        if self._use_stable:
            key = index.lower().replace("_", "-")
            path = f"/{key}-constituent"
        else:
            endpoint_map = {
                "sp500": "/api/v3/sp500_constituent",
                "nasdaq": "/api/v3/nasdaq_constituent",
                "dowjones": "/api/v3/dowjones_constituent",
            }
            path = endpoint_map.get(index.lower(), f"/api/v3/{index}_constituent")
        data = await self._get(path)
        return data if isinstance(data, list) else []

    async def get_sector_performance(self) -> list[dict[str, Any]]:
        """Fetch sector performance summary.

        FMP endpoints:
          - v3:     GET /api/v3/sector-performance
          - stable: GET /stable/sector-performance
        """
        path = "/sector-performance" if self._use_stable else "/api/v3/sector-performance"
        data = await self._get(path)
        return data if isinstance(data, list) else []

    async def get_economic_indicators(
        self, indicator: str, from_date: date | None = None, to_date: date | None = None
    ) -> list[dict[str, Any]]:
        """Fetch macroeconomic indicator time series.

        FMP endpoints:
          - v3:     GET /api/v4/economic?name={indicator}
          - stable: GET /stable/economic-indicator?name={indicator}
        """
        params: dict[str, Any] = {"name": indicator}
        if from_date:
            params["from"] = from_date.isoformat()
        if to_date:
            params["to"] = to_date.isoformat()
        path = "/economic-indicator" if self._use_stable else "/api/v4/economic"
        data = await self._get(path, params)
        return data if isinstance(data, list) else []

    async def get_technical_indicator(
        self, symbol: str, indicator: str, period: int = 14, interval: str = "daily"
    ) -> list[dict[str, Any]]:
        """Fetch pre-computed technical indicator.

        FMP endpoints:
          - v3:     GET /api/v3/technical_indicator/{interval}/{symbol}?type=...&period=...
          - stable: GET /stable/technical-indicator/{interval}?symbol={symbol}&type=...&period=...
        """
        params: dict[str, Any] = {"type": indicator.lower(), "period": period}
        if self._use_stable:
            data = await self._get(
                f"/technical-indicator/{interval}",
                {"symbol": symbol, **params},
            )
        else:
            data = await self._get(
                f"/api/v3/technical_indicator/{interval}/{symbol}", params
            )
        return data if isinstance(data, list) else []

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()


def _map_interval(interval: str) -> str:
    """Map internal interval codes to FMP interval path segments.

    Args:
        interval: Internal interval code (e.g. '1m', '5m', '1h').

    Returns:
        FMP-compatible interval string (e.g. '1min', '5min', '1hour').
    """
    mapping = {
        "1m": "1min",
        "5m": "5min",
        "10m": "10min",
        "15m": "15min",
        "30m": "30min",
        "1h": "1hour",
        "4h": "4hour",
    }
    return mapping.get(interval, interval)
