"""Yahoo Finance (yfinance) API client.

Wraps the `yfinance` library behind the QuantAPIBase interface.
yfinance is synchronous; all methods use asyncio.to_thread() to avoid
blocking the event loop.

No API key required.
"""

import asyncio
from datetime import date
from typing import Any

import yfinance as yf

from app.quant_api.base import QuantAPIBase

# Map generic interval strings to yfinance interval codes
_INTERVAL_MAP: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "60m",
    "4h": "90m",
    "1d": "1d",
    "1wk": "1wk",
    "1mo": "1mo",
}


class YFinanceClient(QuantAPIBase):
    """QuantAPIBase implementation backed by yfinance.

    yfinance does not expose index constituents, sector performance, or
    pre-computed technical indicators natively — those methods return
    empty collections as graceful no-ops.
    """

    def __init__(self) -> None:
        """Initialize YFinanceClient (no credentials required)."""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ticker(self, symbol: str) -> yf.Ticker:
        """Return a yfinance Ticker instance.

        Args:
            symbol: Ticker symbol (e.g. 'AAPL').
        """
        return yf.Ticker(symbol)

    # ------------------------------------------------------------------
    # QuantAPIBase implementation
    # ------------------------------------------------------------------

    async def get_company_profile(self, symbol: str) -> dict[str, Any]:
        """Fetch company profile via yfinance Ticker.info.

        Args:
            symbol: Ticker symbol.

        Returns:
            Dict with companyName, exchange, sector, industry, mktCap, description, etc.
        """
        info: dict[str, Any] = await asyncio.to_thread(
            lambda: self._ticker(symbol).info
        )
        return {
            "symbol": symbol,
            "companyName": info.get("longName", ""),
            "exchange": info.get("exchange", ""),
            "exchangeShortName": info.get("exchange", ""),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "mktCap": info.get("marketCap"),
            "price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "beta": info.get("beta"),
            "description": info.get("longBusinessSummary", ""),
            "country": info.get("country", ""),
            "website": info.get("website", ""),
            "employees": info.get("fullTimeEmployees"),
            "ipoDate": info.get("firstTradeDateEpochUtc"),
            # valuation ratios
            "peRatioTTM": info.get("trailingPE"),
            "forwardPE": info.get("forwardPE"),
            "pbRatioTTM": info.get("priceToBook"),
            "psRatioTTM": info.get("priceToSalesTrailing12Months"),
            "pegRatio": info.get("pegRatio"),
            "eps": info.get("trailingEps"),
            "epsDiluted": info.get("trailingEps"),
            # dividends
            "dividendYield": info.get("dividendYield"),
            "dividendRate": info.get("dividendRate"),
            "payoutRatio": info.get("payoutRatio"),
            # ownership / float
            "sharesOutstanding": info.get("sharesOutstanding"),
            "floatShares": info.get("floatShares"),
            "shortRatio": info.get("shortRatio"),
            # analyst consensus
            "targetMeanPrice": info.get("targetMeanPrice"),
            "numberOfAnalystOpinions": info.get("numberOfAnalystOpinions"),
            # profitability & margins (available in Ticker.info)
            "returnOnEquity": info.get("returnOnEquity"),
            "returnOnAssets": info.get("returnOnAssets"),
            "grossMargins": info.get("grossMargins"),
            "operatingMargins": info.get("operatingMargins"),
            "profitMargins": info.get("profitMargins"),
            # income statement / balance sheet highlights
            "totalRevenue": info.get("totalRevenue"),
            "ebitda": info.get("ebitda"),
            "netIncomeToCommon": info.get("netIncomeToCommon"),
            "debtToEquity": info.get("debtToEquity"),
            "totalDebt": info.get("totalDebt"),
            "totalCash": info.get("totalCash"),
            "currentRatio": info.get("currentRatio"),
            "quickRatio": info.get("quickRatio"),
            "bookValue": info.get("bookValue"),
            # growth rates (stored for context)
            "revenueGrowth": info.get("revenueGrowth"),
            "earningsGrowth": info.get("earningsGrowth"),
            "isin": None,
            "cik": None,
        }

    async def get_historical_prices(
        self, symbol: str, from_date: date, to_date: date, interval: str = "1d"
    ) -> list[dict[str, Any]]:
        """Fetch OHLCV bars via yfinance Ticker.history().

        Args:
            symbol: Ticker symbol.
            from_date: Start date (inclusive).
            to_date: End date (inclusive).
            interval: Bar interval ('1d', '1h', '15m', etc.).

        Returns:
            List of dicts with date, open, high, low, close, volume.
        """
        yf_interval = _INTERVAL_MAP.get(interval, "1d")

        def _fetch() -> list[dict[str, Any]]:
            df = self._ticker(symbol).history(
                start=from_date.isoformat(),
                end=to_date.isoformat(),
                interval=yf_interval,
                auto_adjust=True,
            )
            if df.empty:
                return []
            df.index = df.index.astype(str)
            return [
                {
                    "date": idx,
                    "open": row["Open"],
                    "high": row["High"],
                    "low": row["Low"],
                    "close": row["Close"],
                    "volume": int(row["Volume"]),
                }
                for idx, row in df.iterrows()
            ]

        return await asyncio.to_thread(_fetch)

    async def get_quote(self, symbol: str) -> dict[str, Any]:
        """Fetch current quote fields from Ticker.info.

        Args:
            symbol: Ticker symbol.

        Returns:
            Dict with price, change, changesPercentage, volume, marketCap, etc.
        """
        info: dict[str, Any] = await asyncio.to_thread(
            lambda: self._ticker(symbol).info
        )
        current = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
        prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose") or 0.0
        change = current - prev_close if prev_close else 0.0
        change_pct = (change / prev_close * 100) if prev_close else 0.0
        return {
            "symbol": symbol,
            "price": current,
            "change": round(change, 4),
            "changesPercentage": round(change_pct, 4),
            "volume": info.get("volume") or info.get("regularMarketVolume"),
            "marketCap": info.get("marketCap"),
            "pe": info.get("trailingPE"),
            "eps": info.get("trailingEps"),
            "52WeekHigh": info.get("fiftyTwoWeekHigh"),
            "52WeekLow": info.get("fiftyTwoWeekLow"),
        }

    async def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        """Fetch key financial metrics from Ticker.info.

        Args:
            symbol: Ticker symbol.

        Returns:
            Dict with peRatio, pbRatio, roe, debtToEquity, dividendYield, etc.
        """
        info: dict[str, Any] = await asyncio.to_thread(
            lambda: self._ticker(symbol).info
        )
        return {
            "peRatio": info.get("trailingPE"),
            "forwardPE": info.get("forwardPE"),
            "pbRatio": info.get("priceToBook"),
            "psRatio": info.get("priceToSalesTrailing12Months"),
            "roe": info.get("returnOnEquity"),
            "roa": info.get("returnOnAssets"),
            "debtToEquity": info.get("debtToEquity"),
            "currentRatio": info.get("currentRatio"),
            "quickRatio": info.get("quickRatio"),
            "dividendYield": info.get("dividendYield"),
            "payoutRatio": info.get("payoutRatio"),
            "earningsGrowth": info.get("earningsGrowth"),
            "revenueGrowth": info.get("revenueGrowth"),
            "beta": info.get("beta"),
        }

    async def get_financial_ratios(self, symbol: str) -> dict[str, Any]:
        """Fetch profitability and margin ratios from Ticker.info.

        Args:
            symbol: Ticker symbol.

        Returns:
            Dict with grossProfitMargin, operatingProfitMargin, netProfitMargin, etc.
        """
        info: dict[str, Any] = await asyncio.to_thread(
            lambda: self._ticker(symbol).info
        )
        return {
            "grossProfitMargin": info.get("grossMargins"),
            "operatingProfitMargin": info.get("operatingMargins"),
            "netProfitMargin": info.get("profitMargins"),
            "ebitdaMargin": info.get("ebitdaMargins"),
            "revenueGrowth": info.get("revenueGrowth"),
            "earningsGrowth": info.get("earningsGrowth"),
            "freeCashflow": info.get("freeCashflow"),
            "operatingCashflow": info.get("operatingCashflow"),
        }

    async def get_stock_news(
        self, symbol: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Fetch recent news for a symbol via Ticker.news.

        Args:
            symbol: Ticker symbol. If None, returns empty list (yfinance requires symbol).
            limit: Max articles to return.

        Returns:
            List of dicts with title, publishedDate, url, publisher.
        """
        if not symbol:
            return []

        def _fetch() -> list[dict[str, Any]]:
            raw = self._ticker(symbol).news or []
            results = []
            for item in raw[:limit]:
                content = item.get("content", {})
                results.append(
                    {
                        "title": content.get("title", item.get("title", "")),
                        "publishedDate": content.get("pubDate", ""),
                        "url": content.get("canonicalUrl", {}).get("url", ""),
                        "publisher": content.get("provider", {}).get("displayName", ""),
                        "text": content.get("summary", ""),
                    }
                )
            return results

        return await asyncio.to_thread(_fetch)

    async def get_index_constituents(self, index: str) -> list[dict[str, Any]]:
        """Not natively supported by yfinance — returns empty list.

        Args:
            index: Index identifier (ignored).
        """
        return []

    async def get_sector_performance(self) -> list[dict[str, Any]]:
        """Not natively supported by yfinance — returns empty list."""
        return []

    async def get_economic_indicators(
        self, indicator: str, from_date: date | None = None, to_date: date | None = None
    ) -> list[dict[str, Any]]:
        """Not natively supported by yfinance — returns empty list.

        Args:
            indicator: Indicator name (ignored).
            from_date: Start date (ignored).
            to_date: End date (ignored).
        """
        return []

    async def get_technical_indicator(
        self, symbol: str, indicator: str, period: int = 14, interval: str = "daily"
    ) -> list[dict[str, Any]]:
        """Not pre-computed by yfinance — returns empty list.

        Use the transforms layer (app/quant_api/transforms.py) to compute
        technical indicators from raw OHLCV data.

        Args:
            symbol: Ticker symbol (ignored).
            indicator: Indicator name (ignored).
            period: Lookback period (ignored).
            interval: Bar interval (ignored).
        """
        return []

    async def close(self) -> None:
        """No-op — yfinance uses no persistent connections."""
