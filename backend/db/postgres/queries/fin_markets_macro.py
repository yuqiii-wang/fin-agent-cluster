"""SQL queries for ``fin_markets.macro_instruments``.

Covers loading the fixed-universe instrument list used by the
``analyze_economics`` and ``prepare_index`` LangGraph nodes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from backend.db.postgres.connection import raw_conn
from backend.db.postgres.errors import PG_QUERY_FAILED

logger = logging.getLogger(__name__)

__all__ = ["MacroInstrumentsSQL", "MacroInstrument", "load_macro_instruments"]


@dataclass(frozen=True)
class MacroInstrument:
    """Row from ``fin_markets.macro_instruments``.

    Attributes:
        code:          Short identifier, e.g. ``'gold'``.
        symbol:        Provider ticker, e.g. ``'GC=F'``.
        label:         Human-readable name, e.g. ``'Gold'``.
        category:      ``'economics'`` or ``'market_index'``.
        currency_code: ISO 4217 code, e.g. ``'USD'``.
        zone:          Geo zone: ``'global'``, ``'amer'``, ``'emea'``, or ``'apac'``.
    """

    code: str
    symbol: str
    label: str
    category: str
    currency_code: str
    zone: str


class MacroInstrumentsSQL:
    """Queries against ``fin_markets.macro_instruments``."""

    GET_BY_CATEGORY = """
        SELECT code, symbol, label, category, currency_code, zone
        FROM fin_markets.macro_instruments
        WHERE category = %s
        ORDER BY sort_order
    """


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_cache: dict[str, list[MacroInstrument]] = {}


async def load_macro_instruments(category: str) -> list[MacroInstrument]:
    """Return all instruments for *category*, using an in-process cache.

    Args:
        category: ``'economics'`` or ``'market_index'``.

    Returns:
        Ordered list of :class:`MacroInstrument` rows.  Returns an empty list
        and logs an error on DB failure so callers can degrade gracefully.
    """
    if category in _cache:
        return _cache[category]
    try:
        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(MacroInstrumentsSQL.GET_BY_CATEGORY, (category,))
            rows = await cur.fetchall()
        instruments = [
            MacroInstrument(
                code=row["code"],
                symbol=row["symbol"],
                label=row["label"],
                category=row["category"],
                currency_code=row["currency_code"],
                zone=row["zone"],
            )
            for row in rows
        ]
        _cache[category] = instruments
        return instruments
    except Exception as exc:
        logger.error("[%s] load_macro_instruments failed category=%r: %s", PG_QUERY_FAILED, category, exc)
        return []


async def warm_macro_instruments() -> None:
    """Pre-load all macro instrument categories into the in-process cache.

    Call once at application startup (after DB pools are open) to eliminate
    per-request DB round-trips for instrument lookups.
    """
    for category in ("macro", "market_index"):
        _cache.pop(category, None)
        await load_macro_instruments(category)
