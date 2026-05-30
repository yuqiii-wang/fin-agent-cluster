"""yfinance fundamentals fetcher — extracts fundamental data from ticker.info.

All four endpoint types (income_statement, balance_sheet, cash_flow, key_metrics)
are served from a single ``ticker.info`` call to avoid redundant network requests.
The relevant field subset is returned per endpoint type.

Public API
----------
fetch(symbol, endpoint_type)  — fetch one endpoint's fields from yfinance info.
"""

from __future__ import annotations

import asyncio
import logging
from functools import partial

import yfinance as yf

from backend.resources.stats.errors import STATS_PROVIDER_ERROR, STATS_YFINANCE_EMPTY

logger = logging.getLogger(__name__)

VALID_ENDPOINT_TYPES = frozenset({
    "income_statement",
    "balance_sheet",
    "cash_flow",
    "key_metrics",
})

# Fields extracted per endpoint type from ticker.info
_ENDPOINT_FIELDS: dict[str, list[str]] = {
    "income_statement": [
        "totalRevenue", "grossProfits", "operatingIncome", "netIncome",
        "trailingEps", "revenueGrowth",
    ],
    "balance_sheet": [
        "totalDebt", "totalStockholderEquity",
    ],
    "cash_flow": [
        "freeCashflow",
    ],
    "key_metrics": [
        "trailingPE", "forwardPE", "enterpriseToEbitda",
        "marketCap", "dividendRate",
        "shortName", "longName",
    ],
}


def _extract_info(symbol: str, endpoint_type: str) -> dict:
    """Blocking call: fetch ticker.info and return the relevant field subset.

    Args:
        symbol:        Equity ticker, e.g. ``"AAPL"``.
        endpoint_type: One of the keys in :data:`VALID_ENDPOINT_TYPES`.

    Returns:
        Dict with non-None values for the endpoint's relevant fields.
    """
    ticker = yf.Ticker(symbol)
    info: dict = ticker.info or {}
    fields = _ENDPOINT_FIELDS[endpoint_type]
    return {k: info[k] for k in fields if info.get(k) is not None}


async def fetch(symbol: str, endpoint_type: str) -> dict:
    """Fetch fundamental data for one endpoint type via yfinance.

    Runs the blocking ``yf.Ticker.info`` call in a thread-pool executor.

    Args:
        symbol:        Equity ticker, e.g. ``"AAPL"``.
        endpoint_type: One of ``income_statement``, ``balance_sheet``,
                       ``cash_flow``, ``key_metrics``.

    Returns:
        Dict with relevant non-None fields for the requested endpoint.

    Raises:
        ValueError: When ``endpoint_type`` is unsupported.
        ValueError: When no data is returned from yfinance (``STATS_YFINANCE_EMPTY``).
        ValueError: On unexpected errors (``STATS_PROVIDER_ERROR``).
    """
    if endpoint_type not in VALID_ENDPOINT_TYPES:
        raise ValueError(f"Unsupported endpoint_type '{endpoint_type}' for yfinance fundamentals")

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            partial(_extract_info, symbol, endpoint_type),
        )
    except Exception as exc:
        logger.error(
            "yfinance.fundamentals_fetch error symbol=%s endpoint=%s error=%s [%s]",
            symbol, endpoint_type, exc, STATS_PROVIDER_ERROR,
        )
        raise ValueError(STATS_PROVIDER_ERROR) from exc

    if not result:
        logger.warning(
            "yfinance.fundamentals_fetch empty result symbol=%s endpoint=%s [%s]",
            symbol, endpoint_type, STATS_YFINANCE_EMPTY,
        )
        raise ValueError(STATS_YFINANCE_EMPTY)

    return result


__all__ = ["fetch", "VALID_ENDPOINT_TYPES"]
