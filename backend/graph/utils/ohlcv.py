"""OHLCV stats computation and persistence skill.

Wraps ``compute_quant_stats`` + DB upsert so agent nodes can call a single
function without duplicating infrastructure concerns.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from backend.db import raw_conn
from backend.db.queries.fin_markets_quant import OhlcvStatsSQL
from backend.resource_api.quant_api.models import OHLCVBar
from backend.resource_api.quant_api.ohlcv_processor import compute_quant_stats

logger = logging.getLogger(__name__)

# Regional default currencies — avoids a DB round-trip for the common case.
_REGION_CURRENCY_DEFAULTS: dict[str, str] = {
    "us": "USD", "gb": "GBP", "eu": "EUR", "jp": "JPY",
    "cn": "CNY", "hk": "HKD", "au": "AUD", "ca": "CAD",
    "ch": "CHF", "kr": "KRW", "in": "INR", "sg": "SGD",
    "tw": "TWD", "br": "BRL", "mx": "MXN",
}


async def _resolve_currency_code(region: Optional[str]) -> str:
    """Resolve ISO 4217 currency code for a region, falling back to USD.

    First checks the in-process ``_REGION_CURRENCY_DEFAULTS`` map; if the
    region is not present, queries ``fin_markets.regions`` for the canonical
    value.

    Args:
        region: ``fin_markets.regions`` code, e.g. ``'us'``, ``'cn'``.

    Returns:
        ISO 4217 currency code string (e.g. ``'USD'``).
    """
    if not region:
        return "USD"
    if region in _REGION_CURRENCY_DEFAULTS:
        return _REGION_CURRENCY_DEFAULTS[region]
    async with raw_conn() as conn:
        cur = await conn.execute(
            "SELECT currency_code FROM fin_markets.regions WHERE code = %s LIMIT 1",
            (region,),
        )
        row = await cur.fetchone()
    return row["currency_code"] if row and row["currency_code"] else "USD"


async def get_ohlcv_coverage(
    symbol: str,
    granularity: str,
    since: datetime,
) -> datetime | None:
    """Return the latest ``bar_time`` in *quant_stats* for the given window.

    Args:
        symbol:      Ticker symbol (e.g. ``'AAPL'``).
        granularity: DB granularity string (e.g. ``'15min'``, ``'1day'``, ``'1mo'``).
        since:       Window start — only bars at or after this datetime are considered.

    Returns:
        The latest ``bar_time`` found, or ``None`` if the window is empty.
    """
    async with raw_conn() as conn:
        cur = await conn.execute(
            OhlcvStatsSQL.GET_COVERAGE,
            (symbol.upper(), granularity, since),
        )
        row = await cur.fetchone()
    return row["latest"] if row and row["latest"] else None


async def fetch_ohlcv_from_db(
    symbol: str,
    granularity: str,
    since: datetime,
) -> list[OHLCVBar]:
    """Fetch OHLCV bars from *quant_stats* for the given symbol and window.

    Args:
        symbol:      Ticker symbol (e.g. ``'AAPL'``).
        granularity: DB granularity string (e.g. ``'15min'``, ``'1day'``, ``'1mo'``).
        since:       Window start — only bars at or after this datetime are returned.

    Returns:
        Chronologically ordered list of :class:`OHLCVBar` objects, empty when
        no rows exist in the requested window.
    """
    async with raw_conn() as conn:
        cur = await conn.execute(
            OhlcvStatsSQL.GET_BARS_IN_WINDOW,
            (symbol.upper(), granularity, since),
        )
        rows = await cur.fetchall()

    bars: list[OHLCVBar] = []
    for row in rows:
        bar_time = row["bar_time"]
        date_str = bar_time.isoformat() if hasattr(bar_time, "isoformat") else str(bar_time)
        bars.append(
            OHLCVBar(
                date=date_str,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["volume"] or 0),
            )
        )
    return bars


async def upsert_quant_stats(
    bar_lists: list[list[OHLCVBar]],
    symbol: str,
    source: str,
    interval: str,
    region: Optional[str] = None,
    currency_code: Optional[str] = None,
) -> None:
    """Compute technical indicators and upsert rows into *fin_markets.quant_stats*.

    Args:
        bar_lists:     One or more OHLCV bar sequences to merge before processing.
        symbol:        Ticker symbol (e.g. ``"AAPL"``).
        source:        Data-provider name (e.g. ``"yfinance"``).
        interval:      yfinance interval string (e.g. ``"1d"``, ``"5m"``).
        region:        ``fin_markets.regions`` code (e.g. ``"us"``, ``"jp"``). ``None`` when unknown.
        currency_code: ISO 4217 currency code override.  When ``None``, resolved
                       from ``region`` using :func:`_resolve_currency_code`.
    """
    rows = compute_quant_stats(
        bar_lists=bar_lists, symbol=symbol, source=source, interval=interval
    )
    if not rows:
        return
    resolved_currency = currency_code or await _resolve_currency_code(region)
    for row in rows:
        row["region"] = region
        row["currency_code"] = resolved_currency
    async with raw_conn() as conn:
        async with conn.cursor() as cur:
            await cur.executemany(OhlcvStatsSQL.UPSERT, rows)
    logger.info("[upsert_quant_stats] upserted %d rows for symbol=%s", len(rows), symbol)
