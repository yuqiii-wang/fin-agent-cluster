"""Instrument type definitions and symbol-to-type resolution for quant analysis.

Supported types mirror the ``instrument_type`` CHECK constraint in
``fin_markets.quant_stats``:

* ``'equity'``         — exchange-listed stocks and ETFs (e.g. ``'AAPL'``, ``'005930.KS'``).
* ``'crypto'``         — cryptocurrency spot pairs (e.g. ``'BTC-USD'``, ``'ETH-USD'``).
* ``'commodity'``      — commodity futures tickers (e.g. ``'NG=F'``, ``'CL=F'``).
* ``'precious_metal'`` — precious metal futures tickers (e.g. ``'GC=F'``, ``'SI=F'``).
* ``'index'``          — market-benchmark index tickers (e.g. ``'^GSPC'``, ``'000300.SS'``).
* ``'futures'``        — dated derivative contracts with explicit contract_ticker.
* ``'options'``        — options flow snapshots.
"""

from __future__ import annotations

from typing import Literal

__all__ = [
    "InstrumentType",
    "INSTRUMENT_TYPES",
    "resolve_instrument_type",
]

# ---------------------------------------------------------------------------
# Type alias — valid instrument_type values for quant_stats
# ---------------------------------------------------------------------------

InstrumentType = Literal["equity", "crypto", "commodity", "precious_metal", "index", "futures", "options"]

INSTRUMENT_TYPES: tuple[str, ...] = (
    "equity",
    "crypto",
    "commodity",
    "precious_metal",
    "index",
    "futures",
    "options",
)

# ---------------------------------------------------------------------------
# Known symbol registries (hardcoded from fin_markets.macro_instruments)
# ---------------------------------------------------------------------------

# Crypto spot pairs tracked in macro_instruments (code ∈ {'bitcoin', 'ethereum'}).
_CRYPTO_SYMBOLS: frozenset[str] = frozenset({
    "BTC-USD",   # Bitcoin
    "ETH-USD",   # Ethereum
})

# Precious metal futures tickers tracked in macro_instruments (code ∈ {'gold', 'silver'}).
_PRECIOUS_METAL_SYMBOLS: frozenset[str] = frozenset({
    "GC=F",   # Gold
    "SI=F",   # Silver
})

# Commodity futures tickers tracked in macro_instruments (code ∈ {'nat_gas', 'oil'}).
_COMMODITY_FUTURES_SYMBOLS: frozenset[str] = frozenset({
    "NG=F",   # Natural Gas
    "CL=F",   # Crude Oil (WTI)
})


# ---------------------------------------------------------------------------
# Resolution helper
# ---------------------------------------------------------------------------

def resolve_instrument_type(symbol: str, *, is_index: bool = False) -> InstrumentType:
    """Determine the ``instrument_type`` value for *symbol*.

    Resolution order
    ----------------
    1. ``is_index=True`` **or** symbol starts with ``'^'`` → ``'index'``.
       The ``'^'`` prefix is the universal Yahoo Finance convention for index tickers
       (e.g. ``'^DJI'``, ``'^GSPC'``, ``'^HSI'``).
    2. Symbol in :data:`_CRYPTO_SYMBOLS`            → ``'crypto'``.
    3. Symbol in :data:`_PRECIOUS_METAL_SYMBOLS`    → ``'precious_metal'``.
    4. Symbol in :data:`_COMMODITY_FUTURES_SYMBOLS` → ``'commodity'``.
    5. Everything else                              → ``'equity'``.

    The ``is_index`` flag is kept as a separate parameter to avoid importing
    the DB-backed :func:`~backend.db.postgres.queries.fin_markets_indexes.is_index_ticker`
    from this pure-computation module.

    Args:
        symbol:   Ticker symbol (case-insensitive).
        is_index: Pass ``True`` when :func:`is_index_ticker` returns ``True``
                  for this symbol.

    Returns:
        One of ``'equity'``, ``'crypto'``, ``'precious_metal'``, ``'commodity'``, ``'index'``.
    """
    sym = symbol.upper()
    if is_index or sym.startswith("^"):
        return "index"
    if sym in _CRYPTO_SYMBOLS:
        return "crypto"
    if sym in _PRECIOUS_METAL_SYMBOLS:
        return "precious_metal"
    if sym in _COMMODITY_FUTURES_SYMBOLS:
        return "commodity"
    return "equity"
