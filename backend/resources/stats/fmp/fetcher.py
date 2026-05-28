"""FMP (Financial Modeling Prep) stats fetcher.

Calls the FMP REST API to download OHLCV price history and returns a
:class:`~backend.resources.stats.models.StatsRecord`.

Endpoint selection
------------------
period  label | FMP endpoint used                                  | FMP interval
--------------+----------------------------------------------------+--------------
``1d``        | ``/historical-chart/1hour/{symbol}``              | 1-hour bars
``1w``        | ``/historical-price-full/{symbol}``               | daily
``1mo``       | ``/historical-price-full/{symbol}``               | daily
``3mo``       | ``/historical-price-full/{symbol}``               | daily
``1y``        | ``/historical-price-full/{symbol}``               | daily

Date range is computed at call time relative to *today*.

Public API
----------
fetch(symbol, period, http)  — download, validate, transform, return StatsRecord.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from backend.httpx_client import AsyncClient, HTTPError
from backend.resources.stats.errors import (
    STATS_FMP_AUTH_ERROR,
    STATS_FMP_EMPTY,
    STATS_PROVIDER_ERROR,
)
from backend.resources.stats.fmp.transformer import transform
from backend.resources.stats.models import StatsRecord

logger = logging.getLogger(__name__)

# Mapping: period label → (days_back, fmp_intraday_interval or None)
# When fmp_intraday_interval is None, the daily endpoint is used.
_PERIOD_CONFIG: dict[str, tuple[int, str | None]] = {
    "1d":  (5,   "1hour"),
    "1w":  (30,  None),
    "1mo": (90,  None),
    "3mo": (180, None),
    "1y":  (730, None),
    "2y":  (730, None),
}


async def fetch(
    symbol: str,
    period: str,
    http: AsyncClient,
) -> StatsRecord:
    """Download OHLCV data from FMP and return a :class:`StatsRecord`.

    Args:
        symbol: Equity ticker, e.g. ``"AAPL"``.
        period: Aggregation period — one of ``1d``, ``1w``, ``1mo``, ``3mo``, ``1y``.
        http:   Shared :class:`httpx.AsyncClient` pre-configured with
                ``base_url`` and any required proxy / mounts.

    Returns:
        :class:`~backend.resources.stats.models.StatsRecord` with OHLCV series.

    Raises:
        ValueError: When FMP returns HTTP 401/403 (carries
            :data:`~backend.resources.stats.errors.STATS_FMP_AUTH_ERROR`).
        ValueError: When FMP returns an empty dataset (carries
            :data:`~backend.resources.stats.errors.STATS_FMP_EMPTY`).
        ValueError: On unexpected HTTP errors (carries
            :data:`~backend.resources.stats.errors.STATS_PROVIDER_ERROR`).
    """
    if period not in _PERIOD_CONFIG:
        raise ValueError(f"Unsupported period '{period}' for FMP provider")

    days_back, intraday_interval = _PERIOD_CONFIG[period]
    to_date = date.today()
    from_date = to_date - timedelta(days=days_back)
    from_str = from_date.isoformat()
    to_str = to_date.isoformat()

    if intraday_interval:
        url = f"/historical-chart/{intraday_interval}/{symbol.upper()}"
    else:
        url = f"/historical-price-full/{symbol.upper()}"

    logger.info(
        "fmp.fetch symbol=%s period=%s url=%s from=%s to=%s",
        symbol, period, url, from_str, to_str,
    )

    try:
        response = await http.get(url, params={"from": from_str, "to": to_str})
    except HTTPError as exc:
        logger.error(
            "fmp.fetch network error symbol=%s error=%s [%s]",
            symbol, exc, STATS_PROVIDER_ERROR,
        )
        raise ValueError(STATS_PROVIDER_ERROR) from exc

    if response.status_code in (401, 403):
        resp_body = response.text[:500]
        logger.error(
            "fmp.fetch auth error symbol=%s status=%d body=%r [%s]",
            symbol, response.status_code, resp_body, STATS_FMP_AUTH_ERROR,
        )
        raise ValueError(f"{STATS_FMP_AUTH_ERROR}: status={response.status_code} body={resp_body!r}")

    if not response.is_success:
        resp_body = response.text[:500]
        logger.error(
            "fmp.fetch unexpected error symbol=%s status=%d body=%r [%s]",
            symbol, response.status_code, resp_body, STATS_PROVIDER_ERROR,
        )
        raise ValueError(f"{STATS_PROVIDER_ERROR}: status={response.status_code} body={resp_body!r}")

    raw = response.json()

    # Validate that there are actual rows before transforming.
    _check_non_empty(symbol, period, raw)

    record = transform(symbol, period, raw)
    row_count = len(record.content.timestamps)
    logger.info("fmp.fetch ok symbol=%s period=%s rows=%d", symbol, period, row_count)
    return record


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_non_empty(symbol: str, period: str, raw: dict | list) -> None:
    """Raise :class:`ValueError` with STATS_FMP_EMPTY when ``raw`` has no rows.

    Args:
        symbol: Equity ticker (used in the log message).
        period: Period label (used in the log message).
        raw:    Parsed JSON response from FMP.
    """
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, dict):
        rows = raw.get("historical") or []
    else:
        rows = []

    if not rows:
        logger.warning(
            "fmp.fetch empty response symbol=%s period=%s [%s]",
            symbol, period, STATS_FMP_EMPTY,
        )
        raise ValueError(STATS_FMP_EMPTY)
