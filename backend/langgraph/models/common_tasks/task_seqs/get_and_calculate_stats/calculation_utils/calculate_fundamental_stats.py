"""calculate_fundamental_stats — aggregate multi-endpoint fundamentals and upsert quant_static_stats.

Accepts a list of raw JSON dicts, one per fetched fundamental endpoint
(income_statement, balance_sheet, cash_flow, key_metrics), normalises field
names from both FMP and yfinance conventions, merges them into a single
fundamental snapshot, and upserts a row into ``fin_markets.quant_static_stats``
anchored on ``(symbol, fin_report_date)``.

Public exports
--------------
``CalculateFundamentalStatsInput``    — Pydantic input model.
``CalculateFundamentalStatsOutput``   — Pydantic output model.
``calculate_fundamental_stats_handler`` — Celery-layer async handler function.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from backend.db.postgres import raw_conn
from backend.db.postgres.queries.fin_markets_indexes import (
    derive_yf_exchange_from_ticker,
    get_indexes_for_exchange,
)
from backend.db.postgres.queries.fin_markets_static import QuantStaticStatsSQL
from backend.langgraph.models.common_tasks.errors.codes import (
    FUNDAMENTALS_TASK_CALC_ERROR,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Field normalisation maps
# ---------------------------------------------------------------------------

# Each entry: (canonical_field, [provider_keys_in_priority_order])
_FIELD_MAP: list[tuple[str, list[str]]] = [
    # Income statement
    ("revenue",           ["revenue",         "totalRevenue"]),
    ("revenue_yoy",       ["revenueGrowth"]),                            # decimal → *100 below
    ("gross_profit",      ["grossProfit",      "grossProfits"]),
    ("operating_income",  ["operatingIncome"]),
    ("net_income",        ["netIncome"]),
    ("eps_diluted",       ["epsdiluted",        "eps",           "trailingEps"]),
    # Balance sheet
    ("total_debt",        ["totalDebt"]),
    ("shareholders_equity", ["totalStockholdersEquity", "totalStockholderEquity"]),
    # Cash flow
    ("free_cash_flow",    ["freeCashFlow",     "freeCashflow"]),
    # Valuation / key metrics  (FMP key-metrics-ttm uses *TTM suffix)
    ("pe_ratio",          ["peRatioTTM",       "peRatio",        "trailingPE"]),
    ("forward_pe",        ["forwardPERatioTTM", "forwardPE"]),
    ("ev_ebitda",         ["evToEbitdaTTM",    "enterpriseValueOverEBITDA", "enterpriseToEbitda"]),
    ("market_cap",        ["marketCapTTM",     "marketCap"]),
    ("dividend_per_share", ["dividendPerShareTTM", "dividendPerShare", "dividendRate"]),
]

# Fields where the raw value is a decimal fraction that must be multiplied by 100 → %
_PERCENT_FRACTION_FIELDS = frozenset({"revenue_yoy"})


def _merge_items(items: list[dict]) -> dict:
    """Flatten all endpoint dicts into a single merged dict (first-wins per key).

    Args:
        items: List of raw dicts, one per endpoint type.

    Returns:
        Flat merged dict with all keys from all items.
    """
    merged: dict[str, Any] = {}
    for item in items:
        for k, v in item.items():
            if k not in merged and v is not None:
                merged[k] = v
    return merged


def _extract_canonical(merged: dict) -> dict:
    """Map raw provider keys to canonical ``quant_static_stats`` column names.

    Args:
        merged: Flat merged dict from :func:`_merge_items`.

    Returns:
        Dict keyed by canonical column names; missing fields are ``None``.
    """
    canonical: dict[str, Any] = {}
    for canon_key, provider_keys in _FIELD_MAP:
        for pk in provider_keys:
            if merged.get(pk) is not None:
                val = merged[pk]
                if canon_key in _PERCENT_FRACTION_FIELDS and isinstance(val, (int, float)):
                    val = round(float(val) * 100, 4)
                canonical[canon_key] = val
                break
        if canon_key not in canonical:
            canonical[canon_key] = None
    return canonical


def _extract_fin_report_date(merged: dict) -> datetime | None:
    """Parse the financial report date from the merged dict.

    Args:
        merged: Flat merged dict from :func:`_merge_items`.

    Returns:
        Timezone-aware datetime or ``None``.
    """
    raw_date: str | None = merged.get("date") or merged.get("fillingDate")
    if not raw_date:
        return None
    try:
        dt = datetime.fromisoformat(raw_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class FundamentalsDataItem(BaseModel):
    """One endpoint's raw JSON payload.

    Attributes:
        endpoint_type: One of ``income_statement``, ``balance_sheet``,
                       ``cash_flow``, ``key_metrics``.
        json_data:     Raw dict returned by the provider for this endpoint.
    """

    endpoint_type: str
    json_data: dict = Field(default_factory=dict)


class CalculateFundamentalStatsInput(BaseModel):
    """Input for the calculate_fundamental_stats handler.

    Attributes:
        symbol:      Equity ticker symbol, e.g. ``'AAPL'``.
        items:       List of :class:`FundamentalsDataItem`, one per fetched endpoint.
        yf_exchange: Optional yfinance exchange code (e.g. ``'NMS'``, ``'HKG'``) used to
                     populate index membership columns.  Derived from the ticker suffix
                     when not provided.
    """

    symbol: str
    items: list[FundamentalsDataItem] = Field(default_factory=list)
    yf_exchange: str | None = Field(default=None)


class CalculateFundamentalStatsOutput(BaseModel):
    """Output from the calculate_fundamental_stats handler.

    Attributes:
        row_id:           Database ID of the upserted ``quant_static_stats`` row.
        symbol:           Ticker symbol.
        fin_report_date:  Financial report date parsed from the provider data, if available.
    """

    row_id: int
    symbol: str
    fin_report_date: datetime | None = None


# ---------------------------------------------------------------------------
# Celery-layer handler
# ---------------------------------------------------------------------------


async def calculate_fundamental_stats_handler(payload: dict) -> dict:
    """Aggregate multi-endpoint fundamentals and upsert ``quant_static_stats``.

    Steps:
    1. Merge all endpoint dicts into a single flat dict.
    2. Map provider keys to canonical column names.
    3. Derive index membership from ``yf_exchange`` (or ticker suffix fallback).
    4. Upsert into ``quant_static_stats`` anchored on ``(symbol, fin_report_date)``:
       - ``fin_report_date IS NOT NULL`` → INSERT or UPDATE existing row for same period.
       - ``fin_report_date IS NULL``     → plain INSERT (no upsert anchor).

    Args:
        payload: Serialised :class:`CalculateFundamentalStatsInput` dict.

    Returns:
        Serialised :class:`CalculateFundamentalStatsOutput` dict.

    Raises:
        RuntimeError: When the DB upsert fails (carries ``FUNDAMENTALS_TASK_CALC_ERROR``).
    """
    inp = CalculateFundamentalStatsInput.model_validate(payload)
    symbol = inp.symbol.upper()

    merged = _merge_items([item.json_data for item in inp.items])
    canonical = _extract_canonical(merged)
    fin_report_date = _extract_fin_report_date(merged)

    exchange = inp.yf_exchange or derive_yf_exchange_from_ticker(symbol)
    indexes = get_indexes_for_exchange(exchange)
    # primary + up to 3 others
    primary_index_name:      str | None = indexes[0].code if len(indexes) > 0 else None
    other_opt1_index_name:   str | None = indexes[1].code if len(indexes) > 1 else None
    other_opt2_index_name:   str | None = indexes[2].code if len(indexes) > 2 else None
    other_opt3_index_name:   str | None = indexes[3].code if len(indexes) > 3 else None

    try:
        async with raw_conn() as conn:
            cur = await conn.execute(
                QuantStaticStatsSQL.UPSERT,
                {
                    "symbol":                  symbol,
                    "fin_report_date":         fin_report_date,
                    "revenue":                 canonical["revenue"],
                    "revenue_yoy":             canonical["revenue_yoy"],
                    "gross_profit":            canonical["gross_profit"],
                    "operating_income":        canonical["operating_income"],
                    "net_income":              canonical["net_income"],
                    "eps_diluted":             canonical["eps_diluted"],
                    "total_debt":              canonical["total_debt"],
                    "shareholders_equity":     canonical["shareholders_equity"],
                    "free_cash_flow":          canonical["free_cash_flow"],
                    "pe_ratio":                canonical["pe_ratio"],
                    "forward_pe":              canonical["forward_pe"],
                    "ev_ebitda":               canonical["ev_ebitda"],
                    "market_cap":              canonical["market_cap"],
                    "dividend_per_share":      canonical["dividend_per_share"],
                    "dividend_stability":      None,
                    "dividend_record_date":    None,
                    "dividend_payment_date":   None,
                    "published_at":            None,
                    "news_stats_id":           None,
                    "primary_index_name":      primary_index_name,
                    "primary_index_weight":    None,
                    "other_opt1_index_name":   other_opt1_index_name,
                    "other_opt1_index_weight": None,
                    "other_opt2_index_name":   other_opt2_index_name,
                    "other_opt2_index_weight": None,
                    "other_opt3_index_name":   other_opt3_index_name,
                    "other_opt3_index_weight": None,
                    "analysis_estimate_price": None,
                    "analysis_estimate_date":  None,
                },
            )
            row = await cur.fetchone()
    except Exception as exc:
        logger.error(
            "calculate_fundamental_stats DB error symbol=%s error=%s [%s]",
            symbol, exc, FUNDAMENTALS_TASK_CALC_ERROR,
        )
        raise RuntimeError(FUNDAMENTALS_TASK_CALC_ERROR) from exc

    row_id: int = row["id"]
    return CalculateFundamentalStatsOutput(
        row_id=row_id,
        symbol=symbol,
        fin_report_date=fin_report_date,
    ).model_dump(mode="json")


__all__ = [
    "FundamentalsDataItem",
    "CalculateFundamentalStatsInput",
    "CalculateFundamentalStatsOutput",
    "calculate_fundamental_stats_handler",
]
