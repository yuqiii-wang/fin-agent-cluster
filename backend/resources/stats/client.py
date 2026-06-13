"""Stats provider client.

Dispatches market-statistics requests to one of the per-product
services in :mod:`backend.resources.stats.services`, which in turn
route to the appropriate provider implementation (yfinance / FMP /
akshare / mock).

This module is the *thin* entry point used by the rest of the
application:

* Provider selection (which backend to talk to) is driven by ticker
  suffix + ``Settings.STATS_PROVIDER`` (see
  :func:`~backend.resources.stats.routing.provider_for_symbol`).
* Product-type selection (``stock`` / ``index`` / ``futures`` /
  ``macro`` / ``options``) is driven by
  :func:`~backend.resources.stats.services.routing.service_for_symbol`.

Usage::

    from backend.resources.stats.client import StatsClient

    client = StatsClient(symbol="AAPL")
    records = await client.list_stats("AAPL", "1d")
    record  = await client.get_stats("fmp-AAPL-1d")
    await client.aclose()
"""

from __future__ import annotations

import logging
from typing import Optional

from _shared.httpx_client import AsyncClient, make_fmp_async_client, make_mock_transport_async_client
from backend.config import get_settings
from backend.quant.stats.constants import FUTURES_OPTIONS_PERIODS
from backend.resources.stats.models import StatsListResponse, StatsRecord
from backend.resources.stats.providers.mock.transport import MockStatsTransport
from backend.resources.stats.routing import provider_for_symbol
from backend.resources.stats.services.routing import (
    ProductService,
    service_for_symbol,
)

logger = logging.getLogger(__name__)


_MOCK_BASE_URL = "http://mock-stats"
_VALID_PROVIDERS = frozenset({"mock", "yfinance", "fmp", "akshare"})


class StatsClient:
    """Async market-stats provider client.

    Responsibilities
    ----------------
    1. Pick a product-type service based on the ticker symbol.
    2. Pick a provider label based on the ticker suffix / settings.
    3. Build an httpx client for providers that need one.
    4. Delegate fetching to the selected service module.

    Attributes:
        provider: Active provider label.
        product:  Active product-type label.
    """

    provider: str
    product: str

    def __init__(
        self,
        symbol: str | None = None,
        force_provider: str | None = None,
        force_product: str | None = None,
        maturity_horizon: FUTURES_OPTIONS_PERIODS | str | int | float | None = None,
    ) -> None:
        """Initialise the client.

        Args:
            symbol:          Ticker symbol, e.g. ``'AAPL'``, ``'0700.HK'``,
                             ``'600519.SS'``, ``'^GSPC'``, ``'CL=F'``.
            force_provider:  Bypass provider routing and use this label
                             directly.  One of ``'mock'``, ``'yfinance'``,
                             ``'fmp'``, ``'akshare'``.
            force_product:   Bypass product-type routing and use this label
                             directly.  One of ``'stock'``, ``'index'``,
                             ``'futures'``, ``'macro'``, ``'options'``.
            maturity_horizon: How far out to pull maturities when the service
                             is time-bounded (options, futures, bonds, repo, ...).
                             Accepts a
                             :class:`~backend.quant.stats.constants.FUTURES_OPTIONS_PERIODS`
                             member, one of its ``display_name`` strings
                             (``'next'``, ``'one week'``, ``'one month'``,
                             ``'one quarter'``, ``'half year'``,
                             ``'one year'``), or a raw number of seconds.
                             ``None`` maps to
                             ``FUTURES_OPTIONS_PERIODS.ONE_YEAR``.
        """
        settings = get_settings()

        # --- Provider selection ---
        if force_provider is not None:
            requested_provider = force_provider.strip().lower()
        else:
            routed = provider_for_symbol(symbol)
            if routed is not None:
                requested_provider = routed
            else:
                requested_provider = (settings.STATS_PROVIDER or "mock").strip().lower()

        if requested_provider not in _VALID_PROVIDERS:
            logger.warning(
                "StatsClient: unknown provider=%r for symbol=%r, falling back to mock",
                requested_provider, symbol,
            )
            requested_provider = "mock"

        if requested_provider == "fmp" and not settings.FMP_API_KEY:
            logger.warning(
                "StatsClient: provider=fmp for symbol=%r but FMP_API_KEY is not set, "
                "falling back to mock",
                symbol,
            )
            requested_provider = "mock"

        self.provider = requested_provider

        # --- Product-type selection ---
        product_label, service_module = service_for_symbol(
            symbol, force_product=force_product,
        )
        self.product = product_label
        self._service: ProductService = service_module
        self._maturity_horizon = maturity_horizon

        # --- httpx client ---
        if self.provider == "mock":
            self._http: Optional[AsyncClient] = make_mock_transport_async_client(
                _MOCK_BASE_URL, MockStatsTransport()
            )
        elif self.provider == "fmp":
            self._http = make_fmp_async_client()
        else:
            # yfinance / akshare manage their own HTTP session internally.
            self._http = None

        logger.info(
            "StatsClient initialised provider=%s product=%s symbol=%r",
            self.provider, self.product, symbol,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def list_stats(
        self,
        symbol: str | None = None,
        period: str | None = None,
        limit: int = 10,
    ) -> StatsListResponse:
        """Fetch a list of stats records, optionally filtered.

        Args:
            symbol: Ticker symbol to filter on, or ``None`` for all.
            period: Aggregation period label, or ``None``.
            limit:  Maximum number of records to return.

        Returns:
            :class:`~backend.resources.stats.models.StatsListResponse`.
        """
        logger.debug(
            "client.list_stats provider=%s product=%s symbol=%s period=%s limit=%d",
            self.provider, self.product, symbol, period, limit,
        )
        if self.product == "options":
            return await self._service.list_stats(
                symbol or "",
                period,
                self.provider,
                self._http,
                limit=limit,
                maturity_horizon=self._maturity_horizon,
            )
        return await self._service.list_stats(
            symbol or "",
            period,
            self.provider,
            self._http,
            limit=limit,
        )

    async def get_stats(self, record_id: str) -> StatsRecord | None:
        """Fetch a single stats record by ID.

        Args:
            record_id: Record ID, typically ``{provider}-{symbol}-{period}``.

        Returns:
            :class:`~backend.resources.stats.models.StatsRecord`, or ``None``.
        """
        logger.debug(
            "client.get_stats provider=%s product=%s id=%s",
            self.provider, self.product, record_id,
        )
        if self.product == "options":
            return await self._service.get_stats(
                record_id, self.provider, self._http,
                maturity_horizon=self._maturity_horizon,
            )
        return await self._service.get_stats(record_id, self.provider, self._http)

    async def aclose(self) -> None:
        """Close the underlying httpx client (if any)."""
        if self._http is not None:
            await self._http.aclose()
