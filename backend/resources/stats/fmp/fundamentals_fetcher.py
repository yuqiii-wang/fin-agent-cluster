"""FMP fundamentals fetcher — income statement, balance sheet, cash flow, key metrics.

Calls four FMP REST endpoints and returns raw data dicts keyed by endpoint type.

Endpoints
---------
``income_statement``  → ``GET /v3/income-statement/{symbol}?limit=1``
``balance_sheet``     → ``GET /v3/balance-sheet-statement/{symbol}?limit=1``
``cash_flow``         → ``GET /v3/cash-flow-statement/{symbol}?limit=1``
``key_metrics``       → ``GET /v3/key-metrics-ttm/{symbol}?limit=1``

Public API
----------
fetch(symbol, endpoint_type, http)  — fetch one endpoint, return raw dict.
"""

from __future__ import annotations

import logging

from _shared.httpx_client import AsyncClient, HTTPError
from backend.resources.stats.errors import (
    STATS_FMP_AUTH_ERROR,
    STATS_FMP_EMPTY,
    STATS_PROVIDER_ERROR,
)

logger = logging.getLogger(__name__)

_ENDPOINT_PATHS: dict[str, str] = {
    "income_statement": "/v3/income-statement/{symbol}",
    "balance_sheet":    "/v3/balance-sheet-statement/{symbol}",
    "cash_flow":        "/v3/cash-flow-statement/{symbol}",
    "key_metrics":      "/v3/key-metrics-ttm/{symbol}",
}

VALID_ENDPOINT_TYPES = frozenset(_ENDPOINT_PATHS)


async def fetch(
    symbol: str,
    endpoint_type: str,
    http: AsyncClient,
) -> dict:
    """Fetch one fundamental data endpoint from FMP.

    Args:
        symbol:        Equity ticker, e.g. ``"AAPL"``.
        endpoint_type: One of ``income_statement``, ``balance_sheet``,
                       ``cash_flow``, ``key_metrics``.
        http:          Shared :class:`httpx.AsyncClient` pre-configured for FMP.

    Returns:
        Raw dict from the first FMP result record.

    Raises:
        ValueError: On HTTP 401/403 (``STATS_FMP_AUTH_ERROR``).
        ValueError: When FMP returns an empty dataset (``STATS_FMP_EMPTY``).
        ValueError: On unexpected HTTP errors (``STATS_PROVIDER_ERROR``).
        ValueError: When ``endpoint_type`` is not in :data:`VALID_ENDPOINT_TYPES`.
    """
    if endpoint_type not in VALID_ENDPOINT_TYPES:
        raise ValueError(f"Unsupported endpoint_type '{endpoint_type}' for FMP fundamentals")

    path_template = _ENDPOINT_PATHS[endpoint_type]
    url = path_template.format(symbol=symbol.upper())
    params: dict = {"limit": 1}

    try:
        response = await http.get(url, params=params)
    except HTTPError as exc:
        logger.error(
            "fmp.fundamentals_fetch network error symbol=%s endpoint=%s error=%s [%s]",
            symbol, endpoint_type, exc, STATS_PROVIDER_ERROR,
        )
        raise ValueError(STATS_PROVIDER_ERROR) from exc

    if response.status_code in (401, 403):
        logger.error(
            "fmp.fundamentals_fetch auth error symbol=%s endpoint=%s status=%s [%s]",
            symbol, endpoint_type, response.status_code, STATS_FMP_AUTH_ERROR,
        )
        raise ValueError(STATS_FMP_AUTH_ERROR)

    if response.status_code != 200:
        logger.error(
            "fmp.fundamentals_fetch unexpected status symbol=%s endpoint=%s status=%s [%s]",
            symbol, endpoint_type, response.status_code, STATS_PROVIDER_ERROR,
        )
        raise ValueError(STATS_PROVIDER_ERROR)

    data = response.json()
    # key_metrics_ttm returns a dict, others return a list
    if isinstance(data, dict):
        if not data:
            logger.warning(
                "fmp.fundamentals_fetch empty dict symbol=%s endpoint=%s [%s]",
                symbol, endpoint_type, STATS_FMP_EMPTY,
            )
            raise ValueError(STATS_FMP_EMPTY)
        return data

    if not data:
        logger.warning(
            "fmp.fundamentals_fetch empty list symbol=%s endpoint=%s [%s]",
            symbol, endpoint_type, STATS_FMP_EMPTY,
        )
        raise ValueError(STATS_FMP_EMPTY)

    return data[0]


__all__ = ["fetch", "VALID_ENDPOINT_TYPES"]
