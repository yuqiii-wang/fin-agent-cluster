"""Catalog and currency queries for the ``fin_markets`` schema.

Covers helper lookups for currency codes and news sector values used
during prompt catalog loading.
"""

from __future__ import annotations

import logging

from backend.db.postgres.connection import raw_conn
from backend.db.postgres.errors import PG_QUERY_FAILED

logger = logging.getLogger(__name__)

__all__ = ["get_currency_codes", "get_news_sector_values"]


async def get_currency_codes() -> set[str]:
    """Return the set of valid ISO 4217 currency codes from ``fin_markets.currencies``.

    Returns:
        Set of uppercase currency code strings, e.g. ``{'USD', 'EUR', 'JPY', ...}``.
        Empty set on DB error.
    """
    try:
        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute("SELECT code FROM fin_markets.currencies ORDER BY code")
            rows = await cur.fetchall()
        return {row["code"] for row in rows}
    except Exception as exc:
        logger.warning("[%s] get_currency_codes DB query failed: %s", PG_QUERY_FAILED, exc)
        return set()


async def get_news_sector_values() -> list[str]:
    """Return the raw ``fin_markets.news_sector`` ENUM values from the DB.

    Used by ``validate_basics`` to match and correct the LLM's ``industry``
    and ``opposite_industry`` fields against the canonical sector list.

    Returns:
        List of lowercase underscore-separated sector strings, e.g.
        ``['technology', 'healthcare', 'financials', ...]``.
        Empty list on DB error.
    """
    try:
        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(
                "SELECT code AS sector FROM fin_markets.news_sectors ORDER BY sort_order"
            )
            rows = await cur.fetchall()
        return [row["sector"] for row in rows]
    except Exception as exc:
        logger.warning("[%s] get_news_sector_values DB query failed: %s", PG_QUERY_FAILED, exc)
        return []
