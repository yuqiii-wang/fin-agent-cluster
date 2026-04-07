"""Abstract base class for quant data API clients.

All concrete providers (FMP, Polygon, AlphaVantage, etc.) implement this interface
so the pipeline layer can swap providers without changing business logic.
"""

from abc import ABC, abstractmethod
from datetime import date
from typing import Any


class QuantAPIBase(ABC):
    """Abstract interface for a financial market data provider."""

    @abstractmethod
    async def get_company_profile(self, symbol: str) -> dict[str, Any]:
        """Fetch company profile / security reference data.

        Returns dict with keys: symbol, companyName, exchange, sector, industry, mktCap, description, etc.
        """
        ...

    @abstractmethod
    async def get_historical_prices(
        self, symbol: str, from_date: date, to_date: date, interval: str = "1d"
    ) -> list[dict[str, Any]]:
        """Fetch OHLCV bars for a security.

        Args:
            symbol: Ticker symbol (e.g. 'AAPL').
            from_date: Start date (inclusive).
            to_date: End date (inclusive).
            interval: Bar interval ('1d', '1h', '15m', etc.).

        Returns list of dicts with keys: date, open, high, low, close, volume.
        """
        ...

    @abstractmethod
    async def get_quote(self, symbol: str) -> dict[str, Any]:
        """Fetch real-time or delayed quote.

        Returns dict with price, change, changesPercentage, volume, marketCap, etc.
        """
        ...

    @abstractmethod
    async def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        """Fetch trailing-twelve-month key financial metrics.

        Returns dict with peRatio, pbRatio, roe, debtToEquity, dividendYield, etc.
        """
        ...

    @abstractmethod
    async def get_financial_ratios(self, symbol: str) -> dict[str, Any]:
        """Fetch TTM financial ratios (profitability, liquidity, leverage).

        Returns dict with grossProfitMargin, operatingProfitMargin, netProfitMargin, etc.
        """
        ...

    @abstractmethod
    async def get_stock_news(
        self, symbol: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Fetch recent stock/market news.

        Args:
            symbol: Optional ticker to filter news (None for general market news).
            limit: Max articles to return.

        Returns list of dicts with title, text, publishedDate, site, url, image.
        """
        ...

    @abstractmethod
    async def get_index_constituents(self, index: str) -> list[dict[str, Any]]:
        """Fetch constituents of a market index (e.g. 'sp500', 'nasdaq').

        Returns list of dicts with symbol, name, sector, subSector, weight.
        """
        ...

    @abstractmethod
    async def get_sector_performance(self) -> list[dict[str, Any]]:
        """Fetch sector/industry performance summary.

        Returns list of dicts with sector, changesPercentage.
        """
        ...

    @abstractmethod
    async def get_economic_indicators(
        self, indicator: str, from_date: date | None = None, to_date: date | None = None
    ) -> list[dict[str, Any]]:
        """Fetch macroeconomic indicator time series (GDP, CPI, unemployment, etc.).

        Returns list of dicts with date, value.
        """
        ...

    @abstractmethod
    async def get_technical_indicator(
        self, symbol: str, indicator: str, period: int = 14, interval: str = "daily"
    ) -> list[dict[str, Any]]:
        """Fetch a pre-computed technical indicator (RSI, SMA, EMA, etc.).

        Returns list of dicts with date and indicator-specific values.
        """
        ...
