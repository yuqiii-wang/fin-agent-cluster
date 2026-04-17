"""Direct-HTTP Stooq provider for quant market data.

Fetches Stooq daily OHLCV data via the public CSV download API, bypassing
``pandas-datareader`` which is incompatible with pandas ≥ 3.x
(``deprecate_kwarg()`` signature change breaks its import).

Stooq CSV endpoint::

    https://stooq.com/q/d/l/?s=<symbol>&d1=<YYYYMMDD>&d2=<YYYYMMDD>&i=d

Supported methods:
  - ``periodic_ohlcv`` / ``daily_ohlcv``: daily bars via Stooq.

Not supported (falls through to fallback providers):
  - ``intraday_ohlcv``: Stooq does not provide intraday bars.
  - ``quote``: no real-time quote endpoint.
  - ``overview``: no company overview endpoint.

Local symbol-candidate rules (applied before network calls):
  - Canonical ``=F`` futures  → ``.F`` suffix  (e.g. ``GC=F`` → ``GC.F``)
  - ``^``-prefixed indices    → also tried without ``^`` (e.g. ``^SPX`` → ``SPX``)
  - Plain US equities         → also tried with ``.US`` suffix
  - Known-broken futures (``NG.F``) include bare contract code as fallback

Symbols mapped to ``None`` in :data:`TICKER_MAP` (not served by Stooq) fall
through to the next provider in the client's fallback chain (typically yfinance):
``NG=F``, ``BTC-USD``, ``ETH-USD``, ``CL=F``, ``^TNX``, ``^IRX``,
``^US1MT``, ``^US6MT``, and the major US/EU equity indices.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from backend.resource_api.quant_api.configs.periods import PERIOD_DAYS
from backend.resource_api.quant_api.configs.ticker_maps.datareader import TICKER_MAP  # noqa: F401
from backend.resource_api.exceptions import ProviderNotFoundError
from backend.resource_api.quant_api.models import OHLCVBar, QuantQuery, QuantResult

logger = logging.getLogger(__name__)


def _parse_date_range(params: dict[str, Any]) -> tuple[str, str]:
    """Derive start/end date strings from query params.

    Args:
        params: Query params (may contain 'period', 'start', 'interval').

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

    period = params.get("period", "1y")
    days = PERIOD_DAYS.get(period, 365)
    start_str = (end_dt - timedelta(days=days)).strftime("%Y-%m-%d")
    return start_str, end_str


def _build_stooq_candidates(symbol: str) -> list[str]:
    """Return an ordered list of Stooq symbol candidates to try for *symbol*.

    Local parsing rules applied in order:
    1. The translated symbol (from :data:`TICKER_MAP`) is always first.
    2. For ``^``-prefixed index symbols, add the variant without ``^``
       (e.g. ``^SPX`` → also try ``SPX``).
    3. For ``.F`` futures, add the bare contract code without the exchange
       suffix (e.g. ``NG.F`` → also try ``NG``).
    4. For plain equities (no ``^``, no ``.``), append the ``.US`` suffix.
    """
    seen: list[str] = [symbol]

    if symbol.startswith("^"):
        bare = symbol[1:]
        if bare not in seen:
            seen.append(bare)
    elif symbol.endswith(".F"):
        base = symbol[:-2]
        if base not in seen:
            seen.append(base)
    elif "." not in symbol:
        us = f"{symbol}.US"
        if us not in seen:
            seen.append(us)

    return seen


_STOOQ_BASE_URL = "https://stooq.com/q/d/l/"
_STOOQ_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,text/csv,*/*",
}


def _fetch_stooq_ohlcv(symbol: str, params: dict[str, Any]) -> QuantResult:
    """Fetch daily OHLCV bars from Stooq via direct HTTP (no pandas-datareader).

    Directly calls the Stooq public CSV download endpoint, avoiding the
    ``pandas-datareader`` ``deprecate_kwarg()`` incompatibility with pandas ≥ 3.

    Tries each candidate returned by :func:`_build_stooq_candidates` in order
    and uses the first that returns non-empty CSV data.

    Args:
        symbol: Stooq-translated ticker symbol (already passed through TICKER_MAP).
        params: Query params (period, start, interval).

    Returns:
        :class:`QuantResult` with daily OHLCV bars sorted ascending by date.

    Raises:
        ProviderNotFoundError: When no data is returned for any symbol candidate.
    """
    start_str, end_str = _parse_date_range(params)
    d1 = start_str.replace("-", "")
    d2 = end_str.replace("-", "")

    candidates = _build_stooq_candidates(symbol)

    raw_rows: list[dict[str, str]] | None = None
    used_symbol = symbol

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for cand in candidates:
            try:
                resp = client.get(
                    _STOOQ_BASE_URL,
                    params={"s": cand, "d1": d1, "d2": d2, "i": "d"},
                    headers=_STOOQ_HEADERS,
                )
                resp.raise_for_status()
                text = resp.text.strip()

                # Stooq returns a short error page or redirect when symbol unknown.
                if not text or "<html" in text[:200].lower():
                    logger.debug("[stooq_direct] HTML/empty response for %s", cand)
                    continue

                reader = csv.DictReader(io.StringIO(text))
                rows = [r for r in reader if r.get("Date")]
                if not rows:
                    logger.debug("[stooq_direct] no CSV rows for %s", cand)
                    continue

                raw_rows = rows
                used_symbol = cand
                break
            except Exception as exc:
                logger.debug("[stooq_direct] fetch failed for %s: %s", cand, exc)

    if not raw_rows:
        raise ProviderNotFoundError(
            "datareader", "stooq_ohlcv", symbol,
            f"no data returned from Stooq for candidates {candidates}",
        )

    bars: list[OHLCVBar] = []
    for row in raw_rows:
        try:
            bars.append(
                OHLCVBar(
                    date=row["Date"],
                    open=round(float(row["Open"]),   6),
                    high=round(float(row["High"]),   6),
                    low=round(float(row["Low"]),     6),
                    close=round(float(row["Close"]), 6),
                    volume=int(float(row.get("Volume") or 0)),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.debug("[stooq_direct] skipping malformed row for %s: %s", used_symbol, exc)

    if not bars:
        raise ProviderNotFoundError(
            "datareader", "stooq_ohlcv", symbol, "all rows were malformed"
        )

    bars.sort(key=lambda b: b.date)
    return QuantResult(
        symbol=symbol.upper(),
        method="daily_ohlcv",
        source="datareader",
        bars=bars,
        fetched_at=datetime.now(timezone.utc),
    )


async def fetch(query: QuantQuery) -> QuantResult:
    """Entry point called by :class:`~backend.resource_api.quant_api.client.QuantClient`.

    Dispatches to the appropriate blocking fetch function inside
    ``asyncio.to_thread`` so the event loop is not blocked.

    Args:
        query: Structured market-data query from the client.

    Returns:
        Normalised :class:`QuantResult`.

    Raises:
        ProviderNotFoundError: For unsupported methods or missing data.
    """
    if query.method in ("periodic_ohlcv", "daily_ohlcv"):
        return await asyncio.to_thread(_fetch_stooq_ohlcv, query.symbol, query.params)

    raise ProviderNotFoundError(
        "datareader", query.method, query.symbol,
        f"method '{query.method}' is not supported by the datareader provider",
    )
