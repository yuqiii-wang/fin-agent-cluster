"""Region-related queries for the ``fin_markets`` schema.

Covers ``fin_markets.regions`` lookups and the :class:`PromptCatalogs`
helper used by the query_optimizer prompt.
"""

from __future__ import annotations

import logging
from typing import Optional

from backend.db.postgres.connection import raw_conn

logger = logging.getLogger(__name__)


async def get_region_by_name(region_name: str) -> Optional[tuple[str, list[str]]]:
    """Return ``(code, [ticker, ...])`` for a region matched by name.

    Looks up ``fin_markets.regions`` by the human-readable ``name`` column
    (case-insensitive).  Used by the query_optimizer to ground the LLM-provided
    region name in actual DB data and fetch the canonical index tickers.

    Args:
        region_name: Human-readable region name from QueryOptimizerOutput, e.g.
                     ``'United States'``, ``'Japan'``.

    Returns:
        ``(code, [ticker, ...])`` tuple, or ``None`` when no row
        matches or the region has no indexes.
    """
    try:
        async with raw_conn() as conn:
            cur = await conn.execute(
                "SELECT code, indexes FROM fin_markets.regions WHERE LOWER(name) = LOWER(%s)",
                (region_name.strip(),),
            )
            row = await cur.fetchone()
        if not row or not row["indexes"]:
            return None
        return row["code"], list(row["indexes"])
    except Exception as exc:
        logger.warning("[get_region_by_name] DB query failed for region=%r: %s", region_name, exc)
        return None


class PromptCatalogs:
    """Catalog strings loaded from the DB for use in LLM prompt templates."""

    regions: str       # Newline-grouped region names by zone
    indexes: str       # Region name → index label list
    sectors: str       # news_sector ENUM values


async def get_prompt_catalogs() -> PromptCatalogs:
    """Load catalog strings for the query_optimizer prompt from the DB.

    Queries:
    - ``fin_markets.regions`` for human-readable region names (grouped by zone)
    - ``fin_markets.regions`` for index labels per region
    - ``fin_markets.news_sector`` ENUM values for GICS sector list

    Returns:
        A :class:`PromptCatalogs` with three pre-formatted strings ready to
        embed in the system prompt.  Falls back to empty strings on DB error
        so the caller can still proceed with a degraded prompt.
    """
    catalogs = PromptCatalogs()
    catalogs.regions = ""
    catalogs.indexes = ""
    catalogs.sectors = ""

    try:
        async with raw_conn() as conn:
            # ── Region names, grouped by zone ─────────────────────────────
            cur = await conn.execute(
                """
                SELECT zone, name
                FROM fin_markets.regions
                WHERE name NOT IN ('Global', 'Americas', 'EMEA', 'Asia-Pacific')
                ORDER BY zone, code
                """
            )
            rows = await cur.fetchall()

        zone_map: dict[str, list[str]] = {}
        for row in rows:
            zone_map.setdefault(row["zone"], []).append(row["name"])
        zone_labels = {"amer": "Americas", "emea": "EMEA", "apac": "Asia-Pacific"}
        catalogs.regions = "\n".join(
            f"{zone_labels.get(zone, zone)}: {', '.join(names)}"
            for zone, names in zone_map.items()
        )
        if catalogs.regions:
            catalogs.regions += "\nAggregate: Global, Americas, EMEA, Asia-Pacific"

        # ── Index tickers per region ─────────────────────────────────────
        async with raw_conn() as conn:
            cur = await conn.execute(
                """
                SELECT name, indexes
                FROM fin_markets.regions
                WHERE indexes IS NOT NULL
                ORDER BY zone, code
                """
            )
            rows = await cur.fetchall()

        idx_lines: list[str] = []
        for row in rows:
            tickers: list[str] = list(row["indexes"]) if row["indexes"] else []
            if tickers:
                idx_lines.append(f"{row['name']}: {', '.join(tickers)}")
        catalogs.indexes = "\n".join(idx_lines)

        # ── news_sector values from news_sectors table ──────────────────────────
        async with raw_conn() as conn:
            cur = await conn.execute(
                "SELECT code AS sector FROM fin_markets.news_sectors ORDER BY sort_order"
            )
            rows = await cur.fetchall()

        sectors: list[str] = [row["sector"].replace("_", " ").title() for row in rows]
        catalogs.sectors = ", ".join(sectors)

    except Exception as exc:
        logger.warning("[get_prompt_catalogs] DB query failed: %s", exc)

    return catalogs


async def get_region_name_to_code() -> dict[str, str]:
    """Return a mapping of lower-cased region names to region codes from the DB.

    Queries all rows in ``fin_markets.regions`` and builds a dict keyed by
    ``LOWER(name)`` → ``code``.  Used as a fallback in query_optimizer when
    the primary DB lookup via ``get_region_by_name`` fails.

    Returns:
        Dict like ``{"united states": "us", "japan": "jp", ...}``.
        Empty dict on DB error (caller falls back to empty string).
    """
    try:
        async with raw_conn() as conn:
            cur = await conn.execute("SELECT code, name FROM fin_markets.regions ORDER BY code")
            rows = await cur.fetchall()
        return {row["name"].lower(): row["code"] for row in rows if row["name"] and row["code"]}
    except Exception as exc:
        logger.warning("[get_region_name_to_code] DB query failed: %s", exc)
        return {}


async def get_region_indexes(region_code: str) -> list[str]:
    """Return the ordered benchmark index tickers for a region from the DB.

    Queries the ``indexes`` column of ``fin_markets.regions`` and returns
    the ticker list in declaration order.

    Falls back to an empty list when the region has no indexes or when the DB
    query fails (non-fatal — the node will just skip index fetching).

    Args:
        region_code: Lower-case region code matching ``fin_markets.regions.code``,
                     e.g. ``'us'``, ``'cn'``, ``'au'``.

    Returns:
        Ordered list of canonical ticker strings for the region.
        First item is the primary benchmark index.
    """
    try:
        async with raw_conn() as conn:
            cur = await conn.execute(
                "SELECT indexes FROM fin_markets.regions WHERE code = %s",
                (region_code.lower(),),
            )
            row = await cur.fetchone()
        if not row or not row["indexes"]:
            return []
        return list(row["indexes"])
    except Exception as exc:
        logger.warning("[get_region_indexes] DB query failed for region=%r: %s", region_code, exc)
        return []


async def get_regions_for_validation() -> list[dict]:
    """Return all region rows needed for validate_basics.

    Fetches ``code``, ``name``, ``indexes``, and ``currency_code`` for
    every row in ``fin_markets.regions`` that has a non-null ``name``.  Used
    by ``validate_basics`` to correct the LLM's region and index fields against
    actual DB values before ``populate_json`` consumes them.

    Returns:
        List of dicts, each with keys:
        - ``code`` (str)
        - ``name`` (str)
        - ``currency_code`` (str, may be empty)
        - ``indexes`` (list[str] of ticker symbols, may be empty)
        Empty list on DB error.
    """
    try:
        async with raw_conn() as conn:
            cur = await conn.execute(
                """
                SELECT code, name, currency_code, indexes
                FROM fin_markets.regions
                WHERE name IS NOT NULL
                ORDER BY code
                """
            )
            rows = await cur.fetchall()
        return [
            {
                "code": row["code"],
                "name": row["name"],
                "currency_code": row["currency_code"] or "",
                "indexes": list(row["indexes"]) if row["indexes"] else [],
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning("[get_regions_for_validation] DB query failed: %s", exc)
        return []


async def get_region_currency_map() -> dict[str, str]:
    """Return a mapping of region code → ISO 4217 currency code from the DB.

    Queries ``fin_markets.regions`` for all rows with a non-null
    ``currency_code`` and returns a dict keyed by region code.  Used by
    ``populate_sec_profile`` as a fallback when the yfinance overview does not
    provide a currency.

    Returns:
        Dict like ``{"us": "USD", "jp": "JPY", ...}``.  Empty dict on DB error.
    """
    try:
        async with raw_conn() as conn:
            cur = await conn.execute(
                "SELECT code, currency_code FROM fin_markets.regions WHERE currency_code IS NOT NULL ORDER BY code"
            )
            rows = await cur.fetchall()
        return {row["code"]: row["currency_code"] for row in rows}
    except Exception as exc:
        logger.warning("[get_region_currency_map] DB query failed: %s", exc)
        return {}


async def get_currency_codes() -> set[str]:
    """Return the set of valid ISO 4217 currency codes from ``fin_markets.currencies``.

    Used by ``validate_basics`` to validate the ``currency_code`` field derived
    from the resolved region row.

    Returns:
        Set of uppercase currency code strings, e.g. ``{'USD', 'EUR', 'JPY', ...}``.
        Empty set on DB error.
    """
    try:
        async with raw_conn() as conn:
            cur = await conn.execute("SELECT code FROM fin_markets.currencies ORDER BY code")
            rows = await cur.fetchall()
        return {row["code"] for row in rows}
    except Exception as exc:
        logger.warning("[get_currency_codes] DB query failed: %s", exc)
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
        async with raw_conn() as conn:
            cur = await conn.execute(
                "SELECT code AS sector FROM fin_markets.news_sectors ORDER BY sort_order"
            )
            rows = await cur.fetchall()
        return [row["sector"] for row in rows]
    except Exception as exc:
        logger.warning("[get_news_sector_values] DB query failed: %s", exc)
        return []


async def get_currency_for_symbol(symbol: str) -> dict | None:
    """Return currency info for a symbol by joining quant_stats → regions → currencies.

    Looks up the most recent ``region`` recorded for *symbol* in
    ``fin_markets.quant_stats``, then joins ``fin_markets.regions`` and
    ``fin_markets.currencies`` to return the full currency record.

    Args:
        symbol: Ticker symbol, e.g. ``'AAPL'``, ``'9984.T'``.

    Returns:
        Dict with keys ``code``, ``name``, ``symbol``, ``decimals``, or
        ``None`` when the symbol has no region data or the DB query fails.
    """
    try:
        async with raw_conn() as conn:
            cur = await conn.execute(
                """
                SELECT c.code, c.name, c.symbol, c.decimals
                FROM fin_markets.quant_stats  qs
                JOIN fin_markets.regions      r  ON r.code = qs.region
                JOIN fin_markets.currencies   c  ON c.code = r.currency_code
                WHERE qs.symbol = %s
                  AND qs.region IS NOT NULL
                ORDER BY qs.bar_time DESC
                LIMIT 1
                """,
                (symbol.upper(),),
            )
            row = await cur.fetchone()
        if not row:
            return None
        return {"code": row["code"], "name": row["name"], "symbol": row["symbol"], "decimals": row["decimals"]}
    except Exception as exc:
        logger.warning("[get_currency_for_symbol] DB query failed for symbol=%r: %s", symbol, exc)
        return None
