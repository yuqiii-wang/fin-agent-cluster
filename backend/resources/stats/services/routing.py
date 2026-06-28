"""Product-type routing for the stats services layer.

Given a ticker symbol (``'AAPL'``, ``'^GSPC'``, ``'CL=F'``,
``'000300.SS'`` ...), :func:`service_for_symbol` returns the service
module that should be used to fetch stats for it.

The canonical product-type detection now lives in
:mod:`backend.resources.stats.symbol_config` — :func:`_detect_product`
here is a thin wrapper that maps the universal labels down to the five
service labels this module exposes (``crypto`` is routed through the
``stock`` service at the transport level because it is structurally
OHLCV; the label is kept separate so downstream viewers / DB write
paths can treat it distinctly).

Product labels
--------------
* ``'stock'``   -- individual equities and A-shares (``AAPL``,
  ``0700.HK``, ``600519.SS``).  This is also the catch-all when no
  more specific product type can be determined.
* ``'index'``   -- market index tickers detected through the
  ``fin_markets.market_indexes`` cache (``^GSPC``, ``^HSI``,
  ``000300.SS`` ...).  Tickers starting with ``^`` are also routed to
  the index service.
* ``'futures'`` -- futures contracts ending with ``=F`` (``CL=F``,
  ``ES=F``, ``YM=F`` ...).
* ``'options'`` -- reserved; currently nothing routes here at the
  ticker-detection level.  Callers that know they need an options chain
  can force the routing via ``force_product``.
* ``'macro'``   -- FX, rates, yield curves and other macro indicators.
  Tickers such as ``EURUSD=X``, ``USDJPY=X`` and ``^TNX`` route here.

Decision order
--------------
1. ``force_product`` when explicitly supplied.
2. Index detection via :func:`symbol_config.detect_product_type`
   (``is_index_ticker`` cache / ``^`` prefix).
3. Futures / crypto / macro / stock — all via the unified
   :func:`symbol_config.detect_product_type` so there is a single
   source of truth.
"""

from __future__ import annotations

import types
from typing import Optional

from backend.db.postgres.queries.fin_markets_indexes import is_index_ticker
from backend.resources.stats import symbol_config as _sym_cfg
from backend.resources.stats.services import futures, index, macro, options, stock


PRODUCT_STOCK = "stock"
PRODUCT_INDEX = "index"
PRODUCT_FUTURES = "futures"
PRODUCT_OPTIONS = "options"
PRODUCT_MACRO = "macro"


VALID_PRODUCTS = frozenset(
    {PRODUCT_STOCK, PRODUCT_INDEX, PRODUCT_FUTURES, PRODUCT_OPTIONS, PRODUCT_MACRO}
)


ProductService = types.ModuleType


def _detect_product(symbol: str | None) -> str:
    """Infer a service-layer product label from *symbol*.

    Delegates to :func:`_sym_cfg.detect_product_type` — the one true
    source of symbol-pattern logic.  The only post-processing step is
    mapping ``PRODUCT_CRYPTO`` down to ``PRODUCT_STOCK`` at the
    *transport* layer: crypto spot tickers (``BTC-USD`` ...) are
    structurally OHLCV and share yfinance/FMP/mock endpoints with
    equities, so they reuse :mod:`services.stock`.  Downstream code
    that cares about the distinction can re-read the canonical label
    from :mod:`symbol_config` directly.
    """

    if not symbol:
        return PRODUCT_STOCK

    is_idx = bool(is_index_ticker(symbol))
    label = _sym_cfg.detect_product_type(symbol, is_index=is_idx)

    if label == _sym_cfg.PRODUCT_CRYPTO:
        return PRODUCT_STOCK
    return label if label in VALID_PRODUCTS else PRODUCT_STOCK


def service_for_symbol(
    symbol: Optional[str] = None,
    force_product: Optional[str] = None,
) -> tuple[str, ProductService]:
    """Return the ``(product_label, service_module)`` for *symbol*.

    Args:
        symbol:         Ticker symbol, e.g. ``'AAPL'``.
        force_product:  When set, bypass detection and use this product
                        label directly.  Must be one of the
                        ``PRODUCT_*`` constants.

    Returns:
        A ``(product_label, service_module)`` tuple.  The returned
        module exposes the public service contract:
        ``list_stats`` / ``get_stats`` / ``supports_provider``.
    """
    if force_product is not None:
        product = force_product.strip().lower()
        if product not in VALID_PRODUCTS:
            product = PRODUCT_STOCK
    else:
        product = _detect_product(symbol)

    if product == PRODUCT_STOCK:
        return product, stock
    if product == PRODUCT_INDEX:
        return product, index
    if product == PRODUCT_FUTURES:
        return product, futures
    if product == PRODUCT_OPTIONS:
        return product, options
    if product == PRODUCT_MACRO:
        return product, macro

    return PRODUCT_STOCK, stock


__all__ = [
    "PRODUCT_STOCK",
    "PRODUCT_INDEX",
    "PRODUCT_FUTURES",
    "PRODUCT_OPTIONS",
    "PRODUCT_MACRO",
    "VALID_PRODUCTS",
    "ProductService",
    "service_for_symbol",
]
