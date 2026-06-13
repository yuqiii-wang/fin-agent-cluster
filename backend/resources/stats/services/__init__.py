"""Per-product service dispatch for stats fetching.

The :mod:`backend.resources.stats.services` package sits between the
:class:`~backend.resources.stats.client.StatsClient` entry point and the
individual provider implementations (``providers/yfinance``,
``providers/fmp``, ``providers/akshare``, ``providers/mock``).

Each sub-module corresponds to one financial product type:

* :mod:`~backend.resources.stats.services.stock`  -- individual equities / A-shares.
* :mod:`~backend.resources.stats.services.index`  -- market index tickers
  (``^GSPC``, ``^HSI``, ``000300.SS`` ...).
* :mod:`~backend.resources.stats.services.futures` -- futures contracts
  (``CL=F``, ``ES=F`` ...).
* :mod:`~backend.resources.stats.services.options` -- options chains.
* :mod:`~backend.resources.stats.services.macro`  -- macro indicators,
  FX, interest rates.

Routing
-------
:func:`~backend.resources.stats.services.routing.service_for_symbol`
decides which service module to hand the request to, based on the
ticker's pattern and (for index tickers) the in-process
``fin_markets.market_indexes`` cache populated by
:func:`~backend.db.postgres.queries.fin_markets_indexes.warm_market_indexes`.

Public contract
---------------
Every service module exposes the same trio of async functions so the
client can invoke them without knowing the concrete implementation::

    async def list_stats(
        symbol: str,
        period: str | None,
        provider: str,
        http: httpx.AsyncClient | None,
    ) -> StatsListResponse: ...

    async def get_stats(
        record_id: str,
        provider: str,
        http: httpx.AsyncClient | None,
    ) -> StatsRecord | None: ...

    def supports_provider(provider: str) -> bool: ...
"""

from __future__ import annotations

from backend.resources.stats.services import futures, index, macro, options, stock
from backend.resources.stats.services.routing import (
    PRODUCT_FUTURES,
    PRODUCT_INDEX,
    PRODUCT_MACRO,
    PRODUCT_OPTIONS,
    PRODUCT_STOCK,
    ProductService,
    service_for_symbol,
)


__all__ = [
    "futures",
    "index",
    "macro",
    "options",
    "stock",
    "PRODUCT_FUTURES",
    "PRODUCT_INDEX",
    "PRODUCT_MACRO",
    "PRODUCT_OPTIONS",
    "PRODUCT_STOCK",
    "ProductService",
    "service_for_symbol",
]
