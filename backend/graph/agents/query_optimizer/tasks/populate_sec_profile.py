"""Task 4 — populate_sec_profile: ensure a sec_profiles row exists for the resolved ticker.

Input:  ticker (str), region (str), security_name (str), thread_id, node_execution_id, provider
Output: None (writes to DB only)

If a ``sec_profiles`` row already exists for the ticker the task is a no-op.
Otherwise the task fetches the yfinance overview and upserts profile fields
(name, intro, biz_regions, symbols, currency_code, region) into
``fin_markets.sec_profiles``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from backend.db import raw_conn
from backend.db.postgres.queries.fin_markets_region import (
    get_region_currency_map,
    get_region_name_to_code,
)
from backend.db.postgres.queries.fin_markets_static import SecProfileSQL
from backend.graph.agents.task_keys import QO_POPULATE_SEC_PROFILE
from backend.sse_notifications import complete_task, create_task, fail_task
from backend.resource_api.quant_api.client import QuantClient
from backend.resource_api.quant_api.models import QuantQuery

logger = logging.getLogger(__name__)

# Known cross-listing symbol pairs: primary → [aliases].
# Populated from known exchange mappings; used to pre-seed ``symbols`` when no
# overview data is available.
_CROSS_LISTING_HINTS: dict[str, list[str]] = {
    "BABA":  ["BABA",  "9988.HK"],
    "JD":    ["JD",    "9618.HK"],
    "PDD":   ["PDD",   "9999.HK"],
    "NIO":   ["NIO",   "9866.HK"],
    "XPEV":  ["XPEV",  "9868.HK"],
    "LI":    ["LI",    "2015.HK"],
    "BIDU":  ["BIDU",  "9888.HK"],
    "NTES":  ["NTES",  "9999.HK"],
}


def _extract_profile_from_overview(
    ticker: str,
    region: Optional[str],
    overview: dict,
    region_name_map: dict[str, str],
    region_currency_map: dict[str, str],
) -> dict:
    """Map a yfinance overview dict to ``sec_profiles`` column values.

    Args:
        ticker:             Primary ticker symbol (already upper-cased).
        region:             Resolved fin_markets.regions code from the query optimizer.
        overview:           Dict from ``QuantResult.overview`` (yfinance info subset).
        region_name_map:    ``{lower_name: code}`` from ``get_region_name_to_code()``.
        region_currency_map: ``{code: currency_code}`` from ``get_region_currency_map()``.

    Returns:
        Dict of column → value ready for ``SecProfileSQL.UPSERT``.
    """
    name: Optional[str] = overview.get("longName")
    intro: Optional[str] = overview.get("longBusinessSummary")
    country: Optional[str] = overview.get("country")
    currency: Optional[str] = overview.get("financialCurrency") or overview.get("currency")

    # biz_regions: start from country; supplement with known region
    biz_region_set: list[str] = []
    if country:
        mapped = region_name_map.get(country.lower())
        if mapped:
            biz_region_set.append(mapped)
    if region and region not in biz_region_set:
        biz_region_set.append(region)

    # Cross-listing symbols
    symbols: list[str] = _CROSS_LISTING_HINTS.get(ticker, [ticker])

    # Derive currency_code from overview or region fallback
    if not currency:
        currency = region_currency_map.get(region or "", "USD")

    return {
        "symbol": ticker,
        "symbols": symbols,
        "region": region,
        "currency_code": currency.upper() if currency else "USD",
        "name": name,
        "biz_regions": biz_region_set,
        "intro": intro,
    }


async def populate_sec_profile(
    ticker: str,
    region: Optional[str],
    security_name: str,
    thread_id: str,
    node_execution_id: int,
    provider: str,
) -> None:
    """Ensure a ``sec_profiles`` row exists for *ticker*; populate it if not.

    Checks the DB first.  If a row already exists the task is a no-op and
    completes immediately.  Otherwise fetches the yfinance overview and upserts
    a row with all available profile fields.

    Args:
        ticker:            Primary ticker symbol (upper-cased by caller).
        region:            Resolved fin_markets.regions code.
        security_name:     Human-readable name from query_optimizer LLM output;
                           used as fallback when yfinance overview is unavailable.
        thread_id:         LangGraph thread id.
        node_execution_id: Parent node-execution id for task tracking.
        provider:          Active LLM provider name for task metadata.
    """
    task_id = await create_task(
        thread_id, QO_POPULATE_SEC_PROFILE, node_execution_id, provider=provider
    )
    try:
        # ── 1. Check if profile already exists ──────────────────────────────
        async with raw_conn() as conn:
            cur = await conn.execute(SecProfileSQL.EXISTS, (ticker,))
            exists = await cur.fetchone()

        if exists:
            await complete_task(
                thread_id, task_id, QO_POPULATE_SEC_PROFILE,
                {"ticker": ticker, "action": "exists"},
            )
            return

        # ── 2. Fetch overview from yfinance ──────────────────────────────────
        qclient = QuantClient()
        overview: dict = {}
        try:
            result = await asyncio.wait_for(
                qclient.fetch(
                    QuantQuery(
                        symbol=ticker,
                        method="overview",
                        params={},
                        thread_id=thread_id,
                        node_name="query_optimizer",
                    ),
                    source="yfinance",
                    region=region,
                ),
                timeout=15.0,
            )
            overview = result.overview or {}
        except Exception as exc:
            logger.warning("[populate_sec_profile] overview fetch failed for %s: %s", ticker, exc)

        # ── 3. Load DB reference maps for country/currency resolution ─────
        region_name_map = await get_region_name_to_code()
        region_currency_map = await get_region_currency_map()

        # ── 4. Build and upsert profile ──────────────────────────────────────
        profile = _extract_profile_from_overview(
            ticker, region, overview, region_name_map, region_currency_map
        )

        # Fall back to LLM security_name when overview had no longName
        if not profile["name"] and security_name:
            profile["name"] = security_name

        async with raw_conn() as conn:
            cur = await conn.execute(SecProfileSQL.UPSERT, profile)
            row = await cur.fetchone()

        logger.info(
            "[populate_sec_profile] upserted sec_profile for %s (id=%s)",
            ticker, row["id"] if row else "?",
        )
        await complete_task(
            thread_id, task_id, QO_POPULATE_SEC_PROFILE,
            {"ticker": ticker, "action": "created", "name": profile.get("name")},
        )
    except Exception as exc:
        logger.warning("[populate_sec_profile] failed for %s: %s", ticker, exc)
        await fail_task(thread_id, task_id, QO_POPULATE_SEC_PROFILE, str(exc))
