"""Provider-agnostic market data service.

Agents and pipelines call ``MarketDataService`` to fetch, normalise, and
persist market data without caring which underlying API provider is used.

Supported providers:
  - ``"auto"``     — yfinance first, falls back to FMP on empty result (default)
  - ``"yfinance"`` — Yahoo Finance via yfinance (no API key required)
  - ``"fmp"``      — Financial Modeling Prep (requires FMP_API_KEY in settings)

Usage (agents)::

    async with MarketDataService() as svc:          # auto = yfinance → FMP
        sec = await svc.ingest_profile("AAPL")      # fetch + persist
        price_ctx = await svc.fetch_price_context("AAPL", from_date, to_date)
        fund_ctx  = await svc.fetch_fundamentals_context("AAPL")
        news_ctx  = await svc.fetch_news_context("AAPL")

Architecture
------------
- ``app/db/repos/`` — all SQL lives here (SQLAlchemy ``text()`` queries)
- ``app/quant_api/ingest.py`` — IngestMixin (ingest_* methods)
- ``app/quant_api/fetch.py``  — FetchMixin  (fetch_*_context methods)
- ``app/quant_api/service.py`` — MarketDataService (wires everything together)
"""

import logging
from collections.abc import Callable, Coroutine
from typing import Any, Literal

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.repos.fundamentals import FundamentalsRepo
from app.db.repos.news import NewsRepo
from app.db.repos.securities import SecurityRepo
from app.db.repos.trades import TradeRepo
from app.db.session import get_session_factory
from app.models.markets.fundamentals import SecurityExtAggregRecord, SecurityExtRecord
from app.models.markets.news import NewsRecord
from app.models.markets.securities import EntityRecord, SecurityRecord
from app.quant_api import transforms
from app.quant_api.base import QuantAPIBase
from app.quant_api.cache import get_cached, log_external, make_cache_key
from app.quant_api.fetch import FetchMixin
from app.quant_api.fmp import FMPClient
from app.quant_api.ingest import IngestMixin
from app.quant_api.yfinance_client import YFinanceClient

logger = logging.getLogger(__name__)

ProviderType = Literal["fmp", "yfinance", "auto"]



class MarketDataService(IngestMixin, FetchMixin):
    """Provider-agnostic market data service.

    Composes IngestMixin and FetchMixin via multiple inheritance so
    the public API is unchanged while all SQL lives in app.db.repos.* and
    all business logic is split between ingest.py and fetch.py.
    """

    def __init__(
        self,
        provider: ProviderType = "auto",
        thread_id: str | None = None,
        node_name: str = "unknown",
    ) -> None:
        """Initialise service with the chosen provider.

        Args:
            provider: 'auto' tries yfinance then FMP; 'yfinance' or 'fmp'.
            thread_id: LangGraph thread id for external_resources logging.
            node_name: Graph node name (e.g. 'market_data_collector').
        """
        settings = get_settings()
        self._provider: ProviderType = provider
        self._client: QuantAPIBase = self._build_client(provider, settings)
        self._fallback_client: QuantAPIBase | None = (
            FMPClient(api_key=settings.FMP_API_KEY, base_url=settings.FMP_BASE_URL)
            if provider == "auto" and settings.FMP_API_KEY
            else None
        )
        # psycopg connection — used exclusively for cache (external_resources)
        self._conn: AsyncConnection | None = None
        self._db_url: str = settings.DATABASE_URL
        self._thread_id: str | None = thread_id
        self._node_name: str = node_name
        self._debug: bool = settings.DEBUG
        # SQLAlchemy session + repos — lazily initialised on first use
        self._session: AsyncSession | None = None
        self._sec_repo: SecurityRepo | None = None
        self._fund_repo: FundamentalsRepo | None = None
        self._trade_repo: TradeRepo | None = None
        self._news_repo: NewsRepo | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_client(provider: ProviderType, settings: Any) -> QuantAPIBase:
        """Instantiate the primary API client for *provider*.

        Args:
            provider: Provider identifier.
            settings: Application settings object.

        Returns:
            Concrete QuantAPIBase implementation.
        """
        if provider == "fmp":
            return FMPClient(api_key=settings.FMP_API_KEY, base_url=settings.FMP_BASE_URL)
        return YFinanceClient()

    def _effective_provider(self, client: QuantAPIBase) -> str:
        """Return 'fmp' or 'yfinance' for a given client instance.

        Args:
            client: The client to inspect.

        Returns:
            Provider name string used for transform dispatch.
        """
        return "fmp" if isinstance(client, FMPClient) else "yfinance"

    async def _ensure_repos(self) -> None:
        """Lazily create the SQLAlchemy session and repository instances."""
        if self._session is None:
            factory = get_session_factory()
            self._session = factory()
            self._sec_repo = SecurityRepo(self._session)
            self._fund_repo = FundamentalsRepo(self._session)
            self._trade_repo = TradeRepo(self._session)
            self._news_repo = NewsRepo(self._session)

    async def _get_conn(self) -> AsyncConnection:
        """Return the shared psycopg connection used for cache operations.

        Returns:
            Open AsyncConnection with dict row factory.
        """
        if self._conn is None or self._conn.closed:
            self._conn = await AsyncConnection.connect(
                self._db_url,
                autocommit=True,
                row_factory=dict_row,
            )
        return self._conn

    async def _ext_call(
        self,
        client: QuantAPIBase,
        method: str,
        input_data: dict[str, Any],
        fn: Callable[[], Coroutine[Any, Any, Any]],
    ) -> Any:
        """Call *fn* with cache-check and DB logging.

        In DEBUG mode a cached response within the last hour is returned
        without hitting the external API.  Every real call is logged to
        fin_agents.external_resources.

        Args:
            client: Client executing the call (used for source name).
            method: API method name (e.g. 'get_company_profile').
            input_data: Serialisable parameter dict.
            fn: Zero-argument async callable that performs the API call.

        Returns:
            API response (from cache or live), or None on error.
        """
        await self._ensure_repos()
        source = self._effective_provider(client)
        cache_key = make_cache_key(source, method, input_data)
        conn = await self._get_conn()

        if self._debug:
            cached = await get_cached(conn, cache_key)
            if cached is not None:
                logger.debug("Cache hit source=%s method=%s %s", source, method, input_data)
                return cached

        try:
            result = await fn()
        except Exception as exc:
            logger.warning("External call failed source=%s method=%s: %s", source, method, exc)
            return None

        await log_external(
            conn, self._thread_id, self._node_name, source, method, input_data, result, cache_key
        )
        return result

    # ------------------------------------------------------------------
    # Transform dispatch helpers (provider-aware)
    # ------------------------------------------------------------------

    def _to_security(self, raw: dict[str, Any], client: QuantAPIBase | None = None) -> SecurityRecord:
        """Normalise a raw company profile dict to SecurityRecord.

        Args:
            raw: Output of client.get_company_profile().
            client: Client that produced *raw* (resolves correct transform).
        """
        p = self._effective_provider(client) if client else self._provider
        return transforms.fmp_profile_to_security(raw) if p == "fmp" else transforms.yf_profile_to_security(raw)

    def _to_entity(self, raw: dict[str, Any], client: QuantAPIBase | None = None) -> EntityRecord:
        """Normalise a raw company profile dict to EntityRecord.

        Args:
            raw: Output of client.get_company_profile().
            client: Client that produced *raw*.
        """
        p = self._effective_provider(client) if client else self._provider
        return transforms.fmp_profile_to_entity(raw) if p == "fmp" else transforms.yf_profile_to_entity(raw)

    def _to_news(self, raw: dict[str, Any], client: QuantAPIBase | None = None) -> NewsRecord:
        """Normalise a raw news article dict to NewsRecord.

        Args:
            raw: Single article dict from client.get_stock_news().
            client: Client that produced *raw*.
        """
        p = self._effective_provider(client) if client else self._provider
        return transforms.fmp_news_to_record(raw) if p == "fmp" else transforms.yf_news_to_record(raw)

    def _to_security_ext(
        self,
        metrics: dict[str, Any],
        ratios: dict[str, Any],
        security_id: int,
        client: QuantAPIBase | None = None,
    ) -> SecurityExtRecord:
        """Normalise metrics + ratios to SecurityExtRecord.

        Args:
            metrics: Output of client.get_key_metrics().
            ratios: Output of client.get_financial_ratios().
            security_id: FK to fin_markets.securities.
            client: Client that produced the data.
        """
        p = self._effective_provider(client) if client else self._provider
        return (
            transforms.fmp_metrics_to_security_ext(metrics, ratios, security_id)
            if p == "fmp"
            else transforms.yf_metrics_to_security_ext(metrics, ratios, security_id)
        )

    def _to_ext_aggreg(
        self,
        metrics: dict[str, Any],
        ratios: dict[str, Any],
        security_ext_id: int,
        client: QuantAPIBase | None = None,
    ) -> SecurityExtAggregRecord:
        """Normalise metrics + ratios to SecurityExtAggregRecord.

        Args:
            metrics: Output of client.get_key_metrics().
            ratios: Output of client.get_financial_ratios().
            security_ext_id: FK to fin_markets.security_exts.
            client: Client that produced the data.
        """
        p = self._effective_provider(client) if client else self._provider
        return (
            transforms.fmp_metrics_to_ext_aggreg(metrics, ratios, security_ext_id)
            if p == "fmp"
            else transforms.yf_metrics_to_ext_aggreg(metrics, ratios, security_ext_id)
        )

    # ------------------------------------------------------------------
    # Public utility
    # ------------------------------------------------------------------

    async def get_security_id(self, symbol: str) -> int | None:
        """Look up the database id for a ticker symbol.

        Args:
            symbol: Ticker symbol.

        Returns:
            Integer id from fin_markets.securities, or None if not found.
        """
        await self._ensure_repos()
        row = await self._sec_repo.get_security(symbol)
        return row["id"] if row else None

    # ------------------------------------------------------------------
    # Context manager / lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the DB session/connection and all API clients."""
        if self._session:
            await self._session.close()
            self._session = None
        if self._conn and not self._conn.closed:
            await self._conn.close()
        await self._client.close()
        if self._fallback_client:
            await self._fallback_client.close()

    async def __aenter__(self) -> "MarketDataService":
        """Enter async context manager — eagerly initialise repos."""
        await self._ensure_repos()
        return self

    async def __aexit__(self, *_: Any) -> None:
        """Exit async context manager and clean up resources."""
        await self.close()
