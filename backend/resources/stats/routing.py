"""Index-driven provider routing for the stats resource.

Determines which market-data provider should serve OHLCV stats for a given
ticker symbol.  Routing is driven by the ``fin_markets.market_indexes`` cache
loaded at startup via
:func:`~backend.db.postgres.queries.fin_markets_indexes.warm_market_indexes`.

The ticker's dot-suffix is used to derive a yfinance exchange code, which is
then matched against the ``yf_exchange_codes`` column of the index with the
lowest ``sort_order`` covering that exchange.  The ``stats_provider`` from
that index is returned.

For any ticker whose exchange code is not covered by any index, callers fall
back to ``Settings.STATS_PROVIDER``.
"""

from __future__ import annotations

from backend.db.postgres.queries.fin_markets_indexes import (
    derive_yf_exchange_from_ticker,
    get_primary_index_for_exchange,
)


def provider_for_symbol(symbol: str | None) -> str | None:
    """Return the designated stats provider for *symbol*, or ``None`` if unmapped.

    Routing is index-driven: the ticker's dot-suffix is mapped to a yfinance
    exchange code, which is looked up in the ``market_indexes`` in-process
    cache.  The ``stats_provider`` of the highest-priority matching index is
    returned.

    Args:
        symbol: Ticker symbol, e.g. ``'AAPL'``, ``'0700.HK'``, ``'600519.SS'``.
                ``None`` is treated as unmapped.

    Returns:
        Provider label (``'fmp'``, ``'yfinance'``, ``'mock'``) when a mapping
        exists, otherwise ``None``.
    """
    if symbol is None:
        return None
    yf_exchange = derive_yf_exchange_from_ticker(symbol)
    index = get_primary_index_for_exchange(yf_exchange)
    return index.stats_provider if index is not None else None


__all__ = ["provider_for_symbol"]
