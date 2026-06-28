"""Index-driven provider routing for the stats resource.

Determines which market-data provider should serve OHLCV stats for a given
ticker symbol.  Routing is driven by:

1. **Per-symbol provider preference** from
   :mod:`backend.resources.stats.symbol_config` — futures / crypto / macro
   symbols have hardcoded preferred providers (e.g. crypto spot goes straight
   to yfinance instead of going through ``mock`` which has zero crypto rows).
2. **Index-driven lookup** via ``fin_markets.market_indexes`` cache loaded
   at startup via
   :func:`~backend.db.postgres.queries.fin_markets_indexes.warm_market_indexes`.
   The ticker's dot-suffix is used to derive a yfinance exchange code, which
   is matched against the ``yf_exchange_codes`` column of the index with the
   lowest ``sort_order`` covering that exchange.  The ``stats_provider`` from
   that index is returned.
3. ``Settings.STATS_PROVIDER`` as the final fallback for anything still
   unmapped.

Public exports
--------------
``provider_for_symbol`` — returns the designated provider label, or
  ``None`` when no explicit mapping exists (callers fall back to settings).
"""

from __future__ import annotations

from backend.db.postgres.queries.fin_markets_indexes import (
    derive_yf_exchange_from_ticker,
    get_primary_index_for_exchange,
)
from backend.resources.stats import symbol_config as _sym_cfg


def provider_for_symbol(symbol: str | None) -> str | None:
    """Return the designated stats provider for *symbol*, or ``None`` if unmapped.

    Routing priority (highest → lowest):
      1. **Per-symbol provider preference** from
         :func:`_sym_cfg.provider_preference_for_symbol`.  This covers futures
         (``GC=F``, ``CL=F``, ``SR3=F`` ...), crypto spot (``BTC-USD``,
         ``ETH-USD`` ...), macro FX/yields (``EURUSD=X``, ``^TNX`` ...) and
         index tickers (``^GSPC`` ...) with their well-known preferred
         providers (usually yfinance) — so they never hit ``mock`` (which
         has zero futures/crypto rows) by accident.
      2. **Index-driven lookup**: the ticker's dot-suffix is mapped to a
         yfinance exchange code, which is looked up in the
         ``market_indexes`` in-process cache.
      3. ``None`` → callers fall back to ``Settings.STATS_PROVIDER``.

    Args:
        symbol: Ticker symbol, e.g. ``'AAPL'``, ``'0700.HK'``, ``'600519.SS'``.
                ``None`` is treated as unmapped.

    Returns:
        Provider label (``'fmp'``, ``'yfinance'``, ``'mock'``) when a mapping
        exists, otherwise ``None``.
    """

    if symbol is None:
        return None

    per_symbol_prefs = _sym_cfg.provider_preference_for_symbol(symbol)
    if per_symbol_prefs:
        return per_symbol_prefs[0]

    yf_exchange = derive_yf_exchange_from_ticker(symbol)
    index = get_primary_index_for_exchange(yf_exchange)
    return index.stats_provider if index is not None else None


__all__ = ["provider_for_symbol"]
