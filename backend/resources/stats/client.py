"""Stats provider client.

Dispatches market-statistics requests to one of three providers:

* ``"mock"``    — in-process mock data via
  :class:`~backend.resources.stats.mock.transport.MockStatsTransport` (default).
* ``"yfinance"``— downloads data from Yahoo Finance using the ``yfinance``
  library (free, no API key required).
* ``"fmp"``     — calls the Financial Modeling Prep REST API
  (requires ``FMP_API_KEY`` in :class:`~backend.config.Settings`).

Provider selection order
------------------------
1. Ticker-suffix routing via :func:`~backend.resources.stats.routing.provider_for_symbol`
   when a ``symbol`` is supplied to the constructor and the suffix has a mapping.
2. ``Settings.STATS_PROVIDER`` global fallback.
3. ``"mock"`` when the resolved provider is unknown or ``"fmp"`` is requested
   without ``FMP_API_KEY`` being set.

Usage::

    from backend.resources.stats.client import StatsClient

    client = StatsClient(symbol="AAPL")   # routes to fmp for US
    records = await client.list_stats("AAPL", "1d")
    record  = await client.get_stats("fmp-aapl-1d")
    await client.aclose()
"""

from __future__ import annotations

import logging
from typing import Optional

from backend.config import get_settings
from backend.httpx_client import AsyncClient, make_fmp_async_client, make_mock_transport_async_client
from backend.resources.stats.errors import STATS_FMP_EMPTY, STATS_YFINANCE_EMPTY
from backend.resources.stats.mock.transport import MockStatsTransport
from backend.resources.stats.models import StatsListResponse, StatsRecord
from backend.resources.stats.routing import provider_for_symbol

logger = logging.getLogger(__name__)

_MOCK_BASE_URL = "http://mock-stats"
_VALID_PROVIDERS = frozenset({"mock", "yfinance", "fmp"})


class StatsClient:
    """Async market-stats provider client.

    Attributes:
        provider: Active provider label — ``"mock"``, ``"yfinance"``, or
                  ``"fmp"``.
    """

    provider: str

    def __init__(self, symbol: str | None = None, force_provider: str | None = None) -> None:
        """Initialise, selecting the provider based on ticker-suffix routing and global settings.

        Provider resolution order:
        0. *force_provider* when explicitly supplied (bypasses routing and global settings).
        1. :func:`~backend.resources.stats.routing.provider_for_symbol` when *symbol*
           is provided and its suffix has a mapping.
        2. ``Settings.STATS_PROVIDER`` global fallback.
        3. ``"mock"`` when the resolved provider is unknown or ``"fmp"`` is requested
           without ``FMP_API_KEY`` being set.

        Args:
            symbol:         Ticker symbol, e.g. ``'AAPL'``, ``'0700.HK'``, ``'600519.SS'``.
                            When ``None``, the global ``Settings.STATS_PROVIDER`` is used.
            force_provider: When set, bypasses routing and uses this provider directly.
                            Must be one of ``"mock"``, ``"yfinance"``, ``"fmp"``.
        """
        settings = get_settings()

        if force_provider is not None:
            requested = force_provider.strip().lower()
        else:
            routed = provider_for_symbol(symbol)
            if routed is not None:
                requested = routed
            else:
                requested = (settings.STATS_PROVIDER or "mock").strip().lower()

        if requested not in _VALID_PROVIDERS:
            logger.warning(
                "StatsClient: unknown provider=%r for symbol=%r, falling back to mock",
                requested,
                symbol,
            )
            requested = "mock"

        if requested == "fmp" and not settings.FMP_API_KEY:
            logger.warning(
                "StatsClient: provider=fmp for symbol=%r but FMP_API_KEY is not set, "
                "falling back to mock",
                symbol,
            )
            requested = "mock"

        self.provider = requested

        # Each provider needs its own httpx client (or None for yfinance which
        # does not use httpx at all).
        if self.provider == "mock":
            self._http: Optional[AsyncClient] = make_mock_transport_async_client(
                _MOCK_BASE_URL, MockStatsTransport()
            )
        elif self.provider == "fmp":
            self._http = make_fmp_async_client()
        else:
            # yfinance — no httpx client needed; the library manages its own
            # HTTP session internally.
            self._http = None

        logger.info("StatsClient initialised provider=%s", self.provider)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def list_stats(
        self,
        symbol: str | None = None,
        period: str | None = None,
        limit: int = 10,
    ) -> StatsListResponse:
        """Fetch a list of stats records, optionally filtered by symbol and period.

        For ``"mock"`` the backing store can return multiple records matching
        the filters.  For real providers (``"yfinance"``, ``"fmp"``) a single
        record is fetched per ``(symbol, period)`` pair; supplying both is
        therefore strongly recommended.

        Args:
            symbol: Equity ticker to filter on, or ``None`` for all.
            period: Aggregation period to filter on, or ``None`` for all.
            limit:  Maximum number of records to return.

        Returns:
            :class:`~backend.resources.stats.models.StatsListResponse`.
        """
        logger.debug(
            "stats.list_stats provider=%s symbol=%s period=%s limit=%d",
            self.provider, symbol, period, limit,
        )

        if self.provider == "mock":
            return await self._list_stats_mock(symbol, period, limit)
        if self.provider == "yfinance":
            return await self._list_stats_yfinance(symbol, period)
        if self.provider == "fmp":
            return await self._list_stats_fmp(symbol, period)

        # Should never reach here — provider is validated in __init__.
        return StatsListResponse(items=[], total=0)

    async def get_stats(self, record_id: str) -> StatsRecord | None:
        """Fetch a single stats record by ID.

        For real providers the ID must follow the pattern
        ``{provider}-{symbol}-{period}`` (e.g. ``"yf-aapl-1d"``).

        Args:
            record_id: Unique record identifier.

        Returns:
            :class:`~backend.resources.stats.models.StatsRecord`, or ``None``
            if not found.
        """
        logger.debug("stats.get_stats provider=%s id=%s", self.provider, record_id)

        if self.provider == "mock":
            return await self._get_stats_mock(record_id)
        if self.provider == "yfinance":
            return await self._get_stats_real(record_id, prefix="yf")
        if self.provider == "fmp":
            return await self._get_stats_real(record_id, prefix="fmp")

        return None

    async def aclose(self) -> None:
        """Close the underlying httpx client (if any)."""
        if self._http is not None:
            await self._http.aclose()

    # ------------------------------------------------------------------
    # Mock dispatch
    # ------------------------------------------------------------------

    async def _list_stats_mock(
        self,
        symbol: str | None,
        period: str | None,
        limit: int,
    ) -> StatsListResponse:
        assert self._http is not None
        params: dict[str, str | int] = {"limit": limit}
        if symbol is not None:
            params["symbol"] = symbol
        if period is not None:
            params["period"] = period
        response = await self._http.get("/stats", params=params)
        if not response.is_success:
            raise ValueError(
                f"stats.list_stats mock failed: status={response.status_code} body={response.text[:500]!r}"
            )
        items = [StatsRecord.model_validate(row) for row in response.json()]
        return StatsListResponse(items=items, total=len(items))

    async def _get_stats_mock(self, record_id: str) -> StatsRecord | None:
        assert self._http is not None
        response = await self._http.get(f"/stats/{record_id}")
        if response.status_code == 404:
            return None
        if not response.is_success:
            raise ValueError(
                f"stats.get_stats mock failed: status={response.status_code} body={response.text[:500]!r}"
            )
        return StatsRecord.model_validate(response.json())

    # ------------------------------------------------------------------
    # yfinance dispatch
    # ------------------------------------------------------------------

    async def _list_stats_yfinance(
        self,
        symbol: str | None,
        period: str | None,
    ) -> StatsListResponse:
        """Fetch a single (symbol, period) record from Yahoo Finance.

        Returns an empty list when ``symbol`` is not provided, since
        yfinance requires an explicit ticker to download data.
        """
        if not symbol:
            logger.debug("stats.list_stats yfinance: symbol required, returning empty")
            return StatsListResponse(items=[], total=0)

        from backend.resources.stats.yfinance.fetcher import fetch as yf_fetch

        periods = [period] if period else ["1d", "1w", "1mo", "3mo", "1y"]
        items: list[StatsRecord] = []
        for p in periods:
            try:
                record = await yf_fetch(symbol, p)
                items.append(record)
            except ValueError as exc:
                if STATS_YFINANCE_EMPTY in str(exc):
                    logger.warning("stats.list_stats yfinance skip period=%s (empty): %s", p, exc)
                else:
                    raise
        return StatsListResponse(items=items, total=len(items))

    # ------------------------------------------------------------------
    # FMP dispatch
    # ------------------------------------------------------------------

    async def _list_stats_fmp(
        self,
        symbol: str | None,
        period: str | None,
    ) -> StatsListResponse:
        """Fetch a single (symbol, period) record from FMP.

        Returns an empty list when ``symbol`` is not provided.
        """
        if not symbol:
            logger.debug("stats.list_stats fmp: symbol required, returning empty")
            return StatsListResponse(items=[], total=0)

        from backend.resources.stats.fmp.fetcher import fetch as fmp_fetch

        assert self._http is not None
        periods = [period] if period else ["1d", "1w", "1mo", "3mo", "1y"]
        items: list[StatsRecord] = []
        for p in periods:
            try:
                record = await fmp_fetch(symbol, p, self._http)
                items.append(record)
            except ValueError as exc:
                if STATS_FMP_EMPTY in str(exc):
                    logger.warning("stats.list_stats fmp skip period=%s (empty): %s", p, exc)
                else:
                    raise
        return StatsListResponse(items=items, total=len(items))

    # ------------------------------------------------------------------
    # Shared real-provider get_stats helper
    # ------------------------------------------------------------------

    async def _get_stats_real(self, record_id: str, prefix: str) -> StatsRecord | None:
        """Parse ``{prefix}-{symbol}-{period}`` and fetch the record.

        Args:
            record_id: Full record identifier, e.g. ``"yf-aapl-1d"``.
            prefix:    Expected provider prefix (``"yf"`` or ``"fmp"``).

        Returns:
            :class:`~backend.resources.stats.models.StatsRecord` or ``None``.
        """
        parts = record_id.split("-", 2)
        if len(parts) != 3 or parts[0] != prefix:
            logger.debug(
                "stats.get_stats %s: unrecognised id format %r", self.provider, record_id
            )
            return None

        _, symbol, period = parts

        try:
            if self.provider == "yfinance":
                from backend.resources.stats.yfinance.fetcher import fetch as yf_fetch
                return await yf_fetch(symbol, period)
            else:
                from backend.resources.stats.fmp.fetcher import fetch as fmp_fetch
                assert self._http is not None
                return await fmp_fetch(symbol, period, self._http)
        except ValueError as exc:
            logger.warning("stats.get_stats %s id=%r: %s", self.provider, record_id, exc)
            return None
