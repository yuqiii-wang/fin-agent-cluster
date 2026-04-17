"""FRED provider — Federal Reserve Economic Data (St. Louis Fed).

Fetches daily reference rates and prices via the FRED public CSV endpoint.
No API key is required.

FRED CSV endpoint::

    https://fred.stlouisfed.org/graph/fredgraph.csv?id={SERIES_ID}&cosd={START}&coed={END}

Supported series (via :data:`~backend.resource_api.quant_api.configs.ticker_maps.fred.TICKER_MAP`):
  - SOFR              — NY FRB Secured Overnight Financing Rate
  - DGS1MO / DGS3MO / DGS6MO / DGS5 / DGS10 / DGS30 — Treasury yields
  - DTB3              — 3-month T-bill discount rate
  - GOLDAMGBD228NLBM  — LBMA Gold Price AM (USD/troy oz)

Since FRED publishes a single daily reference value (not OHLCV), bars are
constructed with open = high = low = close = value and volume = 0.  Missing
values (FRED uses "." for non-publication days such as weekends) are skipped.

Supported methods:
  - ``periodic_ohlcv`` / ``daily_ohlcv``: daily bars via FRED CSV.

Not supported (falls through to fallback providers):
  - ``intraday_ohlcv``: FRED does not publish intraday data.
  - ``quote``: no real-time quote endpoint.
  - ``overview``: no company overview endpoint.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from backend.resource_api.exceptions import ProviderNotFoundError
from backend.resource_api.quant_api.configs.periods import PERIOD_DAYS
from backend.resource_api.quant_api.configs.ticker_maps.fred import TICKER_MAP  # noqa: F401
from backend.resource_api.quant_api.models import OHLCVBar, QuantQuery, QuantResult

logger = logging.getLogger(__name__)

_FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
_FRED_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,text/plain,*/*",
}


def _parse_date_range(params: dict[str, Any]) -> tuple[str, str]:
    """Derive start/end date strings from query params.

    Args:
        params: Query params (may contain 'period', 'start').

    Returns:
        Tuple of (start, end) as ``'YYYY-MM-DD'`` strings.
    """
    end_dt = datetime.now(timezone.utc)
    end_str = end_dt.strftime("%Y-%m-%d")

    if "start" in params:
        try:
            start_dt = datetime.fromisoformat(params["start"].replace("Z", "+00:00"))
            return start_dt.strftime("%Y-%m-%d"), end_str
        except (ValueError, AttributeError):
            pass

    period = params.get("period", "2y")
    days = PERIOD_DAYS.get(period, 730)
    start_str = (end_dt - timedelta(days=days)).strftime("%Y-%m-%d")
    return start_str, end_str


def _fetch_fred_series(series_id: str, canonical_symbol: str, params: dict[str, Any]) -> QuantResult:
    """Fetch a FRED series as daily OHLCV bars via the public CSV endpoint.

    FRED publishes a single daily reference value per series.  The resulting
    :class:`OHLCVBar` objects have ``open == high == low == close == value``
    and ``volume == 0``.  Rows where FRED reports ``"."`` (non-publication
    days) are silently skipped.

    Args:
        series_id:        FRED series identifier, e.g. ``'SOFR'``, ``'DGS10'``.
        canonical_symbol: Original canonical ticker (used in the returned result).
        params:           Query params (period, start).

    Returns:
        :class:`QuantResult` with daily bars sorted ascending by date.

    Raises:
        ProviderNotFoundError: When no data is returned or the series is unknown.
    """
    start_str, end_str = _parse_date_range(params)

    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            resp = client.get(
                _FRED_CSV_URL,
                params={"id": series_id, "cosd": start_str, "coed": end_str},
                headers=_FRED_HEADERS,
            )
            resp.raise_for_status()
            text = resp.text.strip()
    except httpx.HTTPStatusError as exc:
        raise ProviderNotFoundError(
            "fred", "fredgraph_csv", canonical_symbol,
            f"HTTP {exc.response.status_code} for series={series_id}",
        ) from exc

    if not text or "<html" in text[:200].lower():
        raise ProviderNotFoundError(
            "fred", "fredgraph_csv", canonical_symbol,
            f"non-CSV response for series={series_id}",
        )

    reader = csv.reader(io.StringIO(text))
    rows = list(reader)

    # First row is header: ["DATE", "<SERIES_ID>"]
    if len(rows) < 2:
        raise ProviderNotFoundError(
            "fred", "fredgraph_csv", canonical_symbol,
            f"empty CSV for series={series_id}",
        )

    bars: list[OHLCVBar] = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        date_str, value_str = row[0].strip(), row[1].strip()
        if not date_str or value_str in (".", ""):
            # FRED uses "." for missing / non-publication days
            continue
        try:
            value = round(float(value_str), 6)
            bars.append(
                OHLCVBar(
                    date=date_str,
                    open=value,
                    high=value,
                    low=value,
                    close=value,
                    volume=0,
                )
            )
        except (ValueError, TypeError) as exc:
            logger.debug("[fred] skipping malformed row for %s: %s — %s", series_id, row, exc)

    if not bars:
        raise ProviderNotFoundError(
            "fred", "fredgraph_csv", canonical_symbol,
            f"no usable data rows for series={series_id} ({start_str} → {end_str})",
        )

    bars.sort(key=lambda b: b.date)
    return QuantResult(
        symbol=canonical_symbol.upper(),
        method="daily_ohlcv",
        source="fred",
        bars=bars,
        fetched_at=datetime.now(timezone.utc),
    )


async def fetch(query: QuantQuery) -> QuantResult:
    """Entry point called by :class:`~backend.resource_api.quant_api.client.QuantClient`.

    The ``query.symbol`` at this point is already the FRED series ID (translated
    by the client via :data:`~backend.resource_api.quant_api.configs.ticker_maps.fred.TICKER_MAP`).
    The original canonical symbol is not accessible here; the returned
    :class:`QuantResult` uses the translated series ID as its ``symbol``.

    Dispatches the blocking HTTP fetch to a thread so the event loop is not blocked.

    Args:
        query: Structured market-data query (symbol = FRED series ID after translation).

    Returns:
        Normalised :class:`QuantResult` with rate/price bars.

    Raises:
        ProviderNotFoundError: For unsupported methods or when FRED has no data.
    """
    if query.method not in ("periodic_ohlcv", "daily_ohlcv"):
        raise ProviderNotFoundError(
            "fred", query.method, query.symbol,
            f"method '{query.method}' is not supported by the FRED provider",
        )

    return await asyncio.to_thread(
        _fetch_fred_series, query.symbol, query.symbol, query.params
    )
