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
from backend.quant.stats.constants import OPTIONS_PERIODS
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

# Providers that have a fundamentals_fetcher implementation.
_FUNDAMENTALS_PROVIDERS = ("fmp", "yfinance")

# Fallback ordering: the primary provider is tried first, then the rest of
# the chain in priority order. ``mock`` is resolved to ``yfinance`` since
# mock has no fundamentals implementation of its own.
_PROVIDER_FALLBACK_CHAINS: dict[str, list[str]] = {
    "fmp":      ["fmp", "yfinance"],
    "yfinance": ["yfinance", "fmp"],
    "mock":     ["yfinance"],
    "akshare":  ["yfinance", "fmp"],
}


def _fundamentals_provider_chain(symbol: str) -> list[str]:
    """Return the ordered provider chain for fundamentals fetching.

    Uses :func:`provider_for_symbol` for index-driven routing when
    available, else falls back to ``Settings.STATS_PROVIDER``.  ``'mock'``
    is rewritten to ``'yfinance'`` and ``'fmp'`` is dropped when
    ``Settings.FMP_API_KEY`` is not set.
    """
    settings = get_settings()
    primary_raw = provider_for_symbol(symbol) or (settings.STATS_PROVIDER or "yfinance").strip().lower()
    primary = "yfinance" if primary_raw == "mock" else primary_raw
    chain = list(_PROVIDER_FALLBACK_CHAINS.get(primary, [primary]))
    if not settings.FMP_API_KEY:
        chain = [p for p in chain if p != "fmp"]
    # Deduplicate while preserving order and restrict to known impls.
    seen: set[str] = set()
    cleaned: list[str] = []
    for p in chain:
        if p in _FUNDAMENTALS_PROVIDERS and p not in seen:
            seen.add(p)
            cleaned.append(p)
    return cleaned or ["yfinance"]


async def fetch_fundamentals(
    symbol: str,
    endpoint_type: str,
    force_provider: str | None = None,
) -> tuple[str, dict]:
    """Unified fundamentals entry point.

    Provider selection is handled in this module — callers simply pass the
    symbol / endpoint type they want and optionally ``force_provider`` to
    bypass the routing layer.  The unified API:

    1. Resolves the primary provider via :func:`provider_for_symbol`, else
       ``Settings.STATS_PROVIDER``.
    2. Builds a priority fallback chain (``FMP_API_KEY`` is consulted when
       considering ``'fmp'``).
    3. Iterates the chain, invoking the matching
       ``resources.stats.providers.<provider>.fundamentals_fetcher.fetch``
       implementation.
    4. Returns ``(provider_label, raw_dict)`` on the first success, or
       raises :class:`ValueError` carrying ``STATS_PROVIDER_ERROR`` /
       ``*_EMPTY`` if no provider produces data.

    Args:
        symbol:        Equity ticker, e.g. ``'AAPL'``.
        endpoint_type: One of ``income_statement``, ``balance_sheet``,
                       ``cash_flow``, ``key_metrics``.
        force_provider: Optional override to bypass routing.  One of
                        ``'fmp'``, ``'yfinance'``.

    Returns:
        Tuple ``(provider_label, raw_data_dict)``.

    Raises:
        ValueError: When the endpoint type is unsupported or no provider
            yields data (carries one of the ``STATS_*`` error codes).
    """
    from backend.resources.stats.providers.errors import STATS_PROVIDER_ERROR

    valid_endpoints = frozenset({
        "income_statement", "balance_sheet", "cash_flow", "key_metrics",
    })
    if endpoint_type not in valid_endpoints:
        raise ValueError(
            f"[fetch_fundamentals] unsupported endpoint_type='{endpoint_type}'"
        )

    if force_provider:
        chain = [force_provider] if force_provider in _FUNDAMENTALS_PROVIDERS else []
    else:
        chain = _fundamentals_provider_chain(symbol)

    last_error: str | None = None
    for provider in chain:
        try:
            if provider == "fmp":
                from backend.resources.stats.providers.fmp.fundamentals_fetcher import (
                    fetch as _fmp_fetch,
                )
                async with make_fmp_async_client() as http:
                    data = await _fmp_fetch(symbol, endpoint_type, http)
                    return provider, data
            if provider == "yfinance":
                from backend.resources.stats.providers.yfinance.fundamentals_fetcher import (
                    fetch as _yf_fetch,
                )
                data = await _yf_fetch(symbol, endpoint_type)
                return provider, data
        except ValueError as exc:
            last_error = str(exc)
            logger.warning(
                "resources.stats.fetch_fundamentals: provider=%s failed for "
                "symbol=%s endpoint=%s: %s, moving to next provider",
                provider, symbol, endpoint_type, exc,
            )
            continue
        except Exception as exc:  # pragma: no cover - defensive
            last_error = str(exc)
            logger.warning(
                "resources.stats.fetch_fundamentals: provider=%s raised for "
                "symbol=%s endpoint=%s: %s, moving to next provider",
                provider, symbol, endpoint_type, exc,
            )
            continue

    raise ValueError(
        f"[{STATS_PROVIDER_ERROR}] No fundamentals data for symbol={symbol} "
        f"endpoint={endpoint_type} from providers={chain}. Last error: {last_error}"
    )


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
        maturity_horizon: OPTIONS_PERIODS | str | int | float | None = None,
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
                             :class:`~backend.quant.stats.constants.OPTIONS_PERIODS`
                             member, one of its ``display_name`` strings
                             (``'next'``, ``'one week'``, ``'one month'``,
                             ``'one quarter'``, ``'half year'``,
                             ``'one year'``), or a raw number of seconds.
                             ``None`` maps to
                             ``OPTIONS_PERIODS.ONE_YEAR``.
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
