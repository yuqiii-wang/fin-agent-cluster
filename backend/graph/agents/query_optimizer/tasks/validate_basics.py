"""Task 2 — validate_basics: correct LLM basics against SQL static data.

Input:  raw_json (str from comprehend_basics), thread_id, node_execution_id, provider
Output: corrected raw_json (str, same LLMRawContext schema), or None on failure

Corrections applied:
  - ``region``              → exact ``fin_markets.regions.name`` via fuzzy match
  - ``ticker_indexes``      → all index tickers for the resolved region from DB
  - ``industry``            → canonical ``fin_markets.news_sector`` value
  - ``opposite_industry``   → canonical ``fin_markets.news_sector`` value
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from backend.db.queries.fin_markets_region import (
    get_currency_codes,
    get_news_sector_values,
    get_regions_for_validation,
)
from backend.graph.agents.query_optimizer.models import LLMRawContext
from backend.graph.agents.task_keys import QO_VALIDATE_BASICS
from backend.graph.utils.task_stream import complete_task, create_task, fail_task

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Lowercase, strip, and collapse whitespace for loose matching."""
    return " ".join(text.lower().split())


def _correct_region(
    llm_region: str,
    regions: list[dict],
) -> tuple[str, Optional[dict]]:
    """Return the corrected region **code** and its DB row.

    The LLM emits a human-readable name (e.g. "United States").  This
    function resolves it to the canonical ``fin_markets.regions.code``
    (e.g. ``"us"``) that is stored in ``QuantContext.region`` and
    downstream DB tables.

    Matching priority:
    1. Exact case-insensitive match on ``name``.
    2. Exact case-insensitive match on ``code``.
    3. One label is a substring of the other (longest DB name wins).
    4. Falls back to the original LLM value with ``None`` row.

    Args:
        llm_region: Region string from the LLM (e.g. ``"United States"``,
                    ``"US"``, ``"us"``).
        regions:    All rows from ``get_regions_for_validation()``.

    Returns:
        ``(region_code, region_row | None)`` where ``region_code`` matches
        ``fin_markets.regions.code``, e.g. ``"us"``.
    """
    norm_llm = _normalize(llm_region)

    # 1. Exact match on name
    for row in regions:
        if _normalize(row["name"]) == norm_llm:
            return row["code"], row

    # 2. Exact match on code (LLM may already output the code)
    for row in regions:
        if row["code"] == llm_region.strip().lower():
            return row["code"], row

    # 3. Substring match — prefer longest DB name that fits inside the LLM value
    candidates: list[tuple[int, str, dict]] = []
    for row in regions:
        norm_db = _normalize(row["name"])
        if norm_db in norm_llm or norm_llm in norm_db:
            candidates.append((len(norm_db), row["code"], row))

    if candidates:
        candidates.sort(key=lambda t: t[0], reverse=True)
        _, best_code, best_row = candidates[0]
        return best_code, best_row

    return llm_region, None


def _correct_currency(
    currency_code: str,
    valid_codes: set[str],
) -> str:
    """Return the currency code if valid against ``fin_markets.currencies``, else empty string.

    Args:
        currency_code: ISO 4217 code to validate (e.g. ``"USD"``).
        valid_codes:   Set of valid codes from ``get_currency_codes()``.

    Returns:
        Uppercase currency code if found in *valid_codes*, else ``""``.
    """
    if not currency_code:
        return ""
    normalised = currency_code.strip().upper()
    return normalised if normalised in valid_codes else ""


def _correct_sector(llm_sector: str, sectors: list[str]) -> str:
    """Return the best-matching ``fin_markets.news_sector`` value.

    Matching priority:
    1. Exact match after normalising spaces → underscores.
    2. DB sector is a substring of the normalised LLM value.
    3. Normalised LLM value is a substring of the DB sector.
    4. Falls back to the original LLM value.

    Args:
        llm_sector: Sector string from the LLM (e.g. "Financial Services").
        sectors:    Raw enum values from ``get_news_sector_values()``
                    (e.g. ``['technology', 'financials', ...]``).

    Returns:
        Matching sector string, or the original LLM value if no match found.
    """
    if not llm_sector:
        return llm_sector

    norm_llm = _normalize(llm_sector).replace(" ", "_").replace("-", "_")

    # 1. Exact
    if norm_llm in sectors:
        return norm_llm

    # Strip underscores for loose comparison
    stripped_llm = norm_llm.replace("_", "")
    for s in sectors:
        if s.replace("_", "") == stripped_llm:
            return s

    # 2. DB sector substring of LLM
    for s in sectors:
        if s in norm_llm or s.replace("_", " ") in _normalize(llm_sector):
            return s

    # 3. LLM substring of DB sector
    for s in sectors:
        if norm_llm.replace("_", " ") in s.replace("_", " "):
            return s

    return llm_sector


# ---------------------------------------------------------------------------
# Public task
# ---------------------------------------------------------------------------

async def validate_basics(
    raw_json: str,
    thread_id: str,
    node_execution_id: int,
    provider: str,
) -> Optional[str]:
    """Correct region, index, and industry fields in the LLM raw JSON.

    Loads ``fin_markets.regions`` and ``fin_markets.news_sector`` from the DB
    and applies deterministic corrections to the four identity fields that the
    LLM is most likely to get wrong:

    - ``region`` is matched against canonical region names.
    - ``ticker_indexes`` is set to all index tickers for the resolved region from DB.
      Falls back to the LLM-provided value or an empty list if the region is unknown.
    - ``industry`` and ``opposite_industry`` are snapped to the nearest
      ``news_sector`` enum value.

    Args:
        raw_json:          Raw JSON string from ``comprehend_basics``.
        thread_id:         LangGraph thread id.
        node_execution_id: Parent node-execution id for task tracking.
        provider:          Active LLM provider name for task metadata.

    Returns:
        Corrected JSON string (same ``LLMRawContext`` schema) on success,
        or ``None`` on failure.
    """
    task_id = await create_task(
        thread_id, QO_VALIDATE_BASICS, node_execution_id, provider=provider
    )
    try:
        # Parse current LLM output
        ctx = LLMRawContext.model_validate_json(raw_json)
        data: dict = ctx.model_dump()

        # Load static reference data from SQL
        regions = await get_regions_for_validation()
        sectors = await get_news_sector_values()
        valid_currencies = await get_currency_codes()

        # ── Correct region → resolve to fin_markets.regions.code ─────────
        corrected_region, region_row = _correct_region(ctx.region, regions)
        data["region"] = corrected_region

        # ── Derive currency_code from resolved region ─────────────────────
        raw_currency = (region_row or {}).get("currency_code", "") or ""
        data["currency_code"] = _correct_currency(raw_currency, valid_currencies)

        # ── Correct ticker_indexes (list of all index tickers for the region) ──
        if region_row and region_row.get("indexes"):
            data["ticker_indexes"] = list(region_row["indexes"])
        else:
            data["ticker_indexes"] = list(ctx.ticker_indexes) if ctx.ticker_indexes else []

        # ── Correct industry fields ───────────────────────────────────────
        if sectors:
            data["industry"] = _correct_sector(ctx.industry, sectors)
            data["opposite_industry"] = _correct_sector(ctx.opposite_industry, sectors)

        corrected_json = json.dumps(data)

        corrections: dict = {}
        if corrected_region != ctx.region:
            corrections["region"] = {"from": ctx.region, "to": corrected_region}
        if data.get("currency_code"):
            corrections["currency_code"] = {"derived_from_region": corrected_region, "value": data["currency_code"]}
        if data.get("industry") != ctx.industry:
            corrections["industry"] = {"from": ctx.industry, "to": data.get("industry")}
        if data.get("opposite_industry") != ctx.opposite_industry:
            corrections["opposite_industry"] = {"from": ctx.opposite_industry, "to": data.get("opposite_industry")}

        await complete_task(
            thread_id, task_id, QO_VALIDATE_BASICS,
            {"corrections": corrections, "corrected": not bool(corrections)},
        )
        logger.info("[query_optimizer] validate_basics: %s", corrections or "no corrections needed")
        return corrected_json

    except Exception as exc:
        logger.warning("[query_optimizer] validate_basics failed: %s", exc)
        await fail_task(
            thread_id, task_id, QO_VALIDATE_BASICS, str(exc)
        )
        return None
