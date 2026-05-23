"""SQL queries for ``fin_markets.market_indexes`` and ``fin_markets.stock_index_memberships``.

Provides in-process caches for market index metadata and helpers to
detect which indexes a stock belongs to from its yfinance exchange code.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from backend.db.postgres.connection import raw_conn
from backend.db.postgres.errors import PG_QUERY_FAILED

logger = logging.getLogger(__name__)

__all__ = [
    "MarketIndex",
    "load_market_indexes",
    "warm_market_indexes",
    "get_index_by_code",
    "get_indexes_for_exchange",
    "get_primary_index_for_exchange",
    "derive_yf_exchange_from_ticker",
    "upsert_stock_index_memberships",
    "get_symbol_index_codes",
]

# ---------------------------------------------------------------------------
# Ticker-suffix → yfinance exchange code fallback
# Used when yf_exchange is not available (e.g. fmp provider or mock).
# ---------------------------------------------------------------------------
_SUFFIX_TO_YF_EXCHANGE: dict[str, str] = {
    "": "NMS",       # unsuffixed US tickers → NASDAQ (most common)
    ".US": "NMS",    # explicit US suffix
    ".HK": "HKG",    # Hong Kong
    ".SS": "SHH",    # Shanghai
    ".SZ": "SHZ",    # Shenzhen
    ".T": "TYO",     # Tokyo
    ".KS": "KSC",    # Korea KOSPI
    ".KQ": "KSQ",    # Korea KOSDAQ
    ".AX": "ASX",    # Australia
    ".L": "LSE",     # London
    ".DE": "GER",    # Germany XETRA
    ".F": "FRA",     # Frankfurt
    ".PA": "PAR",    # Paris
    ".SW": "SWX",    # Switzerland
    ".TO": "TOR",    # Toronto
    ".NS": "NSI",    # India NSE
    ".BO": "BOM",    # India BSE
    ".SA": "SAO",    # Brazil B3
    ".TW": "TAI",    # Taiwan TWSE
    ".TWO": "TWO",   # Taiwan TPEx
    ".SI": "SGX",    # Singapore
    ".AS": "AMS",    # Amsterdam
    ".MI": "MIL",    # Milan
    ".MC": "MCE",    # Madrid
    ".ST": "STO",    # Stockholm
    ".SR": "SAU",    # Saudi Arabia
    ".JK": "IDX",    # Indonesia
    ".KL": "KLS",    # Malaysia
    ".BK": "SET",    # Thailand
}


# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MarketIndex:
    """Row from ``fin_markets.market_indexes``.

    Attributes:
        code:              Short identifier, e.g. ``'SP500'``, ``'HANG_SENG'``.
        name:              Human-readable name, e.g. ``'S&P 500'``.
        ticker:            Yahoo Finance ticker for the index, e.g. ``'^GSPC'``.
        currency_code:     ISO 4217 code; the traded currency for stocks in this index.
        stats_provider:    Provider to use for OHLCV fetching (``'fmp'`` or ``'yfinance'``).
        zone:              Geographic zone: ``'amer'``, ``'emea'``, or ``'apac'``.
        yf_exchange_codes: yfinance ``info['exchange']`` values for stocks in this index.
        sort_order:        Priority when multiple indexes share exchange codes (lower wins).
    """

    code: str
    name: str
    ticker: str | None
    currency_code: str
    stats_provider: str
    zone: str
    yf_exchange_codes: list[str]
    sort_order: int


# ---------------------------------------------------------------------------
# In-process caches
# ---------------------------------------------------------------------------

_indexes_by_code: dict[str, MarketIndex] = {}
# keyed by each yf_exchange_code string; value is the list of matching indexes
# sorted by sort_order ascending so [0] is always the primary index.
_indexes_by_exchange: dict[str, list[MarketIndex]] = {}


# ---------------------------------------------------------------------------
# Load / warm
# ---------------------------------------------------------------------------

_LOAD_SQL = """
    SELECT code, name, ticker, currency_code, stats_provider, zone,
           yf_exchange_codes, sort_order
    FROM fin_markets.market_indexes
    ORDER BY sort_order
"""


async def load_market_indexes() -> list[MarketIndex]:
    """Load all market indexes from the DB and populate in-process caches.

    Returns:
        List of :class:`MarketIndex` objects ordered by ``sort_order``.
        Returns an empty list and logs an error on DB failure.
    """
    global _indexes_by_code, _indexes_by_exchange
    try:
        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(_LOAD_SQL)
            rows = await cur.fetchall()

        indexes: list[MarketIndex] = [
            MarketIndex(
                code=row["code"],
                name=row["name"],
                ticker=row["ticker"],
                currency_code=row["currency_code"],
                stats_provider=row["stats_provider"],
                zone=row["zone"],
                yf_exchange_codes=list(row["yf_exchange_codes"] or []),
                sort_order=row["sort_order"],
            )
            for row in rows
        ]

        by_code: dict[str, MarketIndex] = {idx.code: idx for idx in indexes}
        by_exchange: dict[str, list[MarketIndex]] = {}
        for idx in indexes:
            for exc in idx.yf_exchange_codes:
                by_exchange.setdefault(exc, []).append(idx)
        # sort each bucket by sort_order so [0] is highest priority
        for exc in by_exchange:
            by_exchange[exc].sort(key=lambda x: x.sort_order)

        _indexes_by_code = by_code
        _indexes_by_exchange = by_exchange
        return indexes
    except Exception as exc:
        logger.error("[%s] load_market_indexes failed: %s", PG_QUERY_FAILED, exc)
        return []


async def warm_market_indexes() -> None:
    """Pre-load market index metadata into in-process caches at startup.

    Must be called after DB connection pools are open.
    """
    _indexes_by_code.clear()
    _indexes_by_exchange.clear()
    await load_market_indexes()


# ---------------------------------------------------------------------------
# Lookup helpers (synchronous — read from cache)
# ---------------------------------------------------------------------------

def get_index_by_code(code: str) -> MarketIndex | None:
    """Return the :class:`MarketIndex` for *code* from the in-process cache, or ``None``.

    Args:
        code: Short identifier, e.g. ``'SP500'``, ``'NASDAQ_100'``.

    Returns:
        Cached :class:`MarketIndex` if found, else ``None``.
        Call :func:`warm_market_indexes` at startup to populate the cache.
    """
    return _indexes_by_code.get(code)


def get_indexes_for_exchange(yf_exchange: str) -> list[MarketIndex]:
    """Return all market indexes that include *yf_exchange* in their ``yf_exchange_codes``.

    Args:
        yf_exchange: Exchange code from ``yfinance`` ``info['exchange']``, e.g. ``'NMS'``, ``'HKG'``.

    Returns:
        List of :class:`MarketIndex` ordered by sort_order (primary first).
        Empty list if no match.
    """
    return list(_indexes_by_exchange.get(yf_exchange, []))


def get_primary_index_for_exchange(yf_exchange: str) -> MarketIndex | None:
    """Return the highest-priority market index for *yf_exchange*, or ``None``.

    Args:
        yf_exchange: Exchange code from ``yfinance`` ``info['exchange']``.

    Returns:
        The :class:`MarketIndex` with the lowest ``sort_order`` that covers
        *yf_exchange*, or ``None`` if no match.
    """
    bucket = _indexes_by_exchange.get(yf_exchange)
    return bucket[0] if bucket else None


def derive_yf_exchange_from_ticker(symbol: str) -> str:
    """Derive a best-guess yfinance exchange code from a ticker symbol's dot-suffix.

    Used as fallback when the yfinance ``info['exchange']`` field is unavailable
    (e.g. for FMP-fetched or mock-provided tickers).

    Args:
        symbol: Ticker symbol, e.g. ``'AAPL'``, ``'0700.HK'``, ``'2330.TW'``.

    Returns:
        Best-guess yfinance exchange code string, defaulting to ``'NMS'`` for
        unsuffixed tickers.
    """
    dot = symbol.rfind(".")
    if dot == -1:
        return _SUFFIX_TO_YF_EXCHANGE.get("", "NMS")
    suffix = symbol[dot:]
    return _SUFFIX_TO_YF_EXCHANGE.get(suffix, "NMS")


# ---------------------------------------------------------------------------
# DB write helpers
# ---------------------------------------------------------------------------

_UPSERT_MEMBERSHIP_SQL = """
    INSERT INTO fin_markets.stock_index_memberships (symbol, index_code, is_primary, upserted_at)
    VALUES (%s, %s, %s, NOW())
    ON CONFLICT (symbol, index_code) DO UPDATE SET
        is_primary  = EXCLUDED.is_primary,
        upserted_at = NOW()
"""

_GET_SYMBOL_MEMBERSHIPS_SQL = """
    SELECT index_code FROM fin_markets.stock_index_memberships
    WHERE symbol = %s
"""


async def upsert_stock_index_memberships(
    symbol: str, yf_exchange: str
) -> MarketIndex | None:
    """Upsert all index memberships for *symbol* based on *yf_exchange*.

    Looks up all market indexes that cover *yf_exchange*, then writes a row for
    each to ``stock_index_memberships``.  The index with the lowest ``sort_order``
    is flagged ``is_primary = TRUE``.

    Args:
        symbol:      Stock ticker, e.g. ``'AAPL'``, ``'0700.HK'``.
        yf_exchange: Exchange code from yfinance, e.g. ``'NMS'``, ``'HKG'``.

    Returns:
        The primary :class:`MarketIndex` if any memberships were written, else ``None``.
    """
    indexes = get_indexes_for_exchange(yf_exchange)
    if not indexes:
        return None

    primary = indexes[0]
    try:
        async with raw_conn() as conn:
            for idx in indexes:
                await conn.execute(
                    _UPSERT_MEMBERSHIP_SQL,
                    (symbol, idx.code, idx.code == primary.code),
                )
        return primary
    except Exception as exc:
        logger.error(
            "[%s] upsert_stock_index_memberships failed symbol=%r exchange=%r: %s",
            PG_QUERY_FAILED, symbol, yf_exchange, exc,
        )
        return None


async def get_symbol_index_codes(symbol: str) -> frozenset[str]:
    """Return all index codes that *symbol* is a member of.

    Args:
        symbol: Stock ticker, e.g. ``'AAPL'``.

    Returns:
        Frozen set of index code strings (empty if no memberships found or on error).
    """
    try:
        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(_GET_SYMBOL_MEMBERSHIPS_SQL, (symbol,))
            rows = await cur.fetchall()
        return frozenset(row["index_code"] for row in rows)
    except Exception as exc:
        logger.error(
            "[%s] get_symbol_index_codes failed symbol=%r: %s",
            PG_QUERY_FAILED, symbol, exc,
        )
        return frozenset()
