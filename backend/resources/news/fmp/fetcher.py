"""FMP (Financial Modeling Prep) news fetcher.

Calls the FMP ``/stable/news`` endpoint and returns a list of
:class:`~backend.resources.news.models.NewsArticle` instances.

Endpoint
--------
``GET /stable/news``

Query parameters
----------------
tickers   — comma-separated tickers, e.g. ``"AAPL"`` (optional)
from      — start date ``YYYY-MM-DD`` (optional)
to        — end date ``YYYY-MM-DD`` (optional)
q         — free-text query used when no ticker is given (optional)
limit     — max articles to return
apikey    — FMP API key (required)
"""

from __future__ import annotations

import logging
from datetime import datetime

from _shared.httpx_client import AsyncClient
from backend.resources.news.errors import (
    NEWS_FMP_AUTH_ERROR,
    NEWS_FMP_EMPTY,
    NEWS_PROVIDER_ERROR,
)
from backend.resources.news.fmp.transformer import transform
from backend.resources.news.models import NewsArticle

logger = logging.getLogger(__name__)


async def fetch(
    symbol: str | None,
    topics: list[str] | None,
    from_dt: datetime | None,
    to_dt: datetime | None,
    limit: int,
    http: AsyncClient,
) -> list[NewsArticle]:
    """Download news articles from FMP and return a list of :class:`NewsArticle`.

    Args:
        symbol:   Primary ticker to filter on, e.g. ``"AAPL"``.  ``None`` to
                  fetch general/topic news.
        topics:   Topic keywords used as free-text ``q`` param when symbol is absent.
        from_dt:  Start of the date window (UTC).  ``None`` to let FMP default.
        to_dt:    End of the date window (UTC).  ``None`` to let FMP default.
        limit:    Maximum number of articles to return.
        http:     Shared :class:`httpx.AsyncClient` pre-configured with
                  ``base_url`` and authentication params (``apikey``).

    Returns:
        List of :class:`~backend.resources.news.models.NewsArticle` instances,
        empty when FMP returns no results.

    Raises:
        ValueError: When FMP returns HTTP 401/403 or an unexpected error.
    """
    params: dict[str, str | int] = {"limit": limit}

    if symbol:
        params["tickers"] = symbol.upper()
    elif topics:
        params["q"] = " ".join(topics)

    if from_dt:
        params["from"] = from_dt.strftime("%Y-%m-%d")
    if to_dt:
        params["to"] = to_dt.strftime("%Y-%m-%d")

    try:
        resp = await http.get("/stable/news", params=params)
    except Exception as exc:
        logger.error("[%s] FMP request failed: %s", NEWS_PROVIDER_ERROR, exc)
        raise ValueError(f"[{NEWS_PROVIDER_ERROR}] FMP request failed: {exc}") from exc

    if resp.status_code in (401, 403):
        logger.error("[%s] FMP auth error status=%d", NEWS_FMP_AUTH_ERROR, resp.status_code)
        raise ValueError(f"[{NEWS_FMP_AUTH_ERROR}] FMP authentication failed (status={resp.status_code})")

    if not resp.is_success:
        logger.error("[%s] FMP error status=%d body=%r", NEWS_PROVIDER_ERROR, resp.status_code, resp.text[:200])
        raise ValueError(f"[{NEWS_PROVIDER_ERROR}] FMP returned status={resp.status_code}")

    raw: list[dict] = resp.json()
    if not raw:
        logger.error("[%s] FMP returned empty for symbol=%s topics=%s", NEWS_FMP_EMPTY, symbol, topics)
        return []

    return transform(raw)
