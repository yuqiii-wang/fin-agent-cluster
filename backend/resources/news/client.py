"""News client: FMP primary, DDGS fallback.

``list_news`` tries FMP first when ``FMP_API_KEY`` is configured; if FMP
returns an empty result set it falls back to ``DDGS().news()``.  ``search``
always uses ``DDGS().text()`` for web-search snippets.

Usage::

    from backend.resources.news.client import NewsClient

    client = NewsClient()
    response = await client.list_news("AAPL")   # FMP -> DDGS fallback
    results  = await client.search("Apple stock outlook")  # always DDGS
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone

from ddgs import DDGS

from backend.config import get_settings
from backend.resources.news.errors import NEWS_NO_RESULTS, NEWS_SEARCH_FAILED
from backend.resources.news.fmp.fetcher import fetch as fmp_fetch
from backend.resources.news.models import InfoResult, NewsArticle, NewsListResponse
from _shared.httpx_client import make_fmp_async_client

logger = logging.getLogger(__name__)

_PROVIDER_FMP = "fmp"
_PROVIDER_DDGS = "ddgs"


def _timelimit_from_dt(from_dt: datetime | None) -> str | None:
    """Convert a lower-bound datetime to a DDGS ``timelimit`` token.

    Args:
        from_dt: Optional start of the date window (UTC).

    Returns:
        One of ``"d"``, ``"w"``, ``"m"``, ``"y"``, or ``None``.
    """
    if from_dt is None:
        return None
    days_ago = (datetime.utcnow() - from_dt.replace(tzinfo=None)).days
    if days_ago <= 1:
        return "d"
    if days_ago <= 7:
        return "w"
    if days_ago <= 31:
        return "m"
    return "y"


def _article_id(url: str | None, title: str) -> str:
    """Build a deterministic article ID from url and title."""
    return "ddgs-" + hashlib.sha256(f"{url or title}".encode()).hexdigest()[:16]


def _parse_ddgs_date(raw: str | None) -> datetime:
    """Parse a DDGS date string to a UTC-aware datetime.

    Args:
        raw: Raw date string from DDGS.

    Returns:
        UTC-aware :class:`datetime`, falling back to ``now`` on parse failure.
    """
    if not raw:
        return datetime.now(tz=timezone.utc)
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    return datetime.now(tz=timezone.utc)


class NewsClient:
    """News and web-search client.

    ``list_news`` tries FMP when ``FMP_API_KEY`` is set; if FMP returns an
    empty result set it automatically falls back to DDGS news search.
    ``search`` always uses DDGS text search.

    Attributes:
        provider: Reflects the provider actually used for the last
                  ``list_news`` call -- ``"fmp"`` or ``"ddgs"``.
    """

    provider: str

    def __init__(self) -> None:
        """Initialise, reading FMP credentials from settings."""
        settings = get_settings()
        self._fmp_api_key: str | None = settings.FMP_API_KEY
        self._fmp_base_url: str = settings.FMP_BASE_URL
        self.provider = _PROVIDER_FMP if self._fmp_api_key else _PROVIDER_DDGS

    async def list_news(
        self,
        symbol: str | None = None,
        topics: list[str] | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        limit: int = 20,
    ) -> NewsListResponse:
        """Fetch news articles, with FMP -> DDGS fallback on empty.

        Tries FMP when ``FMP_API_KEY`` is configured.  Falls back to DDGS
        news search when FMP returns an empty result set (or is not configured).

        Args:
            symbol:  Equity ticker, e.g. ``"AAPL"``.
            topics:  Topic keywords to narrow the search.
            from_dt: Start of the date window (UTC).
            to_dt:   End of the date window (UTC).
            limit:   Maximum number of articles to return.

        Returns:
            :class:`NewsListResponse` with up to *limit* articles.
        """
        if self._fmp_api_key:
            async with make_fmp_async_client() as http:
                try:
                    articles = await fmp_fetch(
                        symbol=symbol,
                        topics=topics,
                        from_dt=from_dt,
                        to_dt=to_dt,
                        limit=limit,
                        http=http,
                    )
                except Exception:
                    articles = []

            if articles:
                self.provider = _PROVIDER_FMP
                return NewsListResponse(items=articles, total=len(articles))

        # FMP empty or not configured -- fall back to DDGS
        return await self._ddgs_news(symbol=symbol, topics=topics, from_dt=from_dt, limit=limit)

    async def _ddgs_news(
        self,
        symbol: str | None,
        topics: list[str] | None,
        from_dt: datetime | None,
        limit: int,
    ) -> NewsListResponse:
        """Fetch news articles from DDGS with query-simplification fallback.

        Tries progressively simpler queries so that verbose LLM-generated topic
        phrases (which can produce 20+ word queries that DuckDuckGo finds nothing
        for) always have a fallback to a plain symbol search.

        Query cascade:
            1. ``symbol + all topics joined``   (full specificity)
            2. ``symbol + first 2 topics``      (reduced noise from long topic lists)
            3. ``symbol`` only                  (guaranteed results for known tickers)
            4. ``"market news"``                (last resort when symbol is None)

        Args:
            symbol:  Equity ticker used as base query.
            topics:  Topic keywords appended to the query.
            from_dt: Start of date window mapped to DDGS timelimit.
            limit:   Maximum number of articles.

        Returns:
            :class:`NewsListResponse`.
        """
        timelimit = _timelimit_from_dt(from_dt)
        loop = asyncio.get_event_loop()

        # Build query variants from most-specific to least-specific.
        candidates: list[str] = []
        if symbol:
            if topics:
                full_parts = [symbol] + list(topics)
                candidates.append(" ".join(full_parts))
                if len(topics) > 2:
                    candidates.append(" ".join([symbol] + list(topics[:2])))
            candidates.append(symbol)
        else:
            if topics:
                candidates.append(" ".join(topics))
            candidates.append("market news")

        raw: list[dict] = []
        for query in candidates:
            try:
                raw = await loop.run_in_executor(
                    None,
                    lambda q=query: list(DDGS().news(q, max_results=limit, timelimit=timelimit)),
                )
            except Exception as exc:
                logger.error("[%s] DDGS news search failed query=%r: %s", NEWS_SEARCH_FAILED, query, exc)
                raw = []
            if raw:
                break
            logger.error("[%s] DDGS news returned no results for query=%r", NEWS_NO_RESULTS, query)

        self.provider = _PROVIDER_DDGS
        if not raw:
            return NewsListResponse(items=[], total=0)

        articles = [
            NewsArticle(
                id=_article_id(r.get("url"), r.get("title", "")),
                symbol=symbol,
                title=r.get("title", ""),
                source=_PROVIDER_DDGS,
                source_name=r.get("source"),
                published_at=_parse_ddgs_date(r.get("date")),
                content=r.get("body", ""),
                url=r.get("url"),
            )
            for r in raw
        ]
        return NewsListResponse(items=articles, total=len(articles))

    async def search(
        self,
        query: str,
        topics: list[str] | None = None,
        from_dt: datetime | None = None,
        max_results: int = 3,
    ) -> list[InfoResult]:
        """Search the web and return up to *max_results* snippets via DDGS text.

        Args:
            query:       Free-form search query.
            topics:      Optional topic keywords appended to *query*.
            from_dt:     Optional lower bound on recency mapped to DDGS timelimit.
            max_results: Maximum number of results to return.

        Returns:
            List of :class:`InfoResult` objects, possibly empty on failure.
        """
        full_query = query
        if topics:
            full_query = f"{query} {' '.join(topics)}"

        timelimit = _timelimit_from_dt(from_dt)

        loop = asyncio.get_event_loop()
        try:
            raw: list[dict] = await loop.run_in_executor(
                None,
                lambda: list(DDGS().text(full_query, max_results=max_results, timelimit=timelimit)),
            )
        except Exception as exc:
            logger.error("[%s] DDGS text search failed query=%r: %s", NEWS_SEARCH_FAILED, full_query, exc)
            return []

        if not raw:
            logger.error("[%s] DDGS text search returned no results for query=%r", NEWS_NO_RESULTS, full_query)
            return []

        return [
            InfoResult(
                url=r.get("href", ""),
                title=r.get("title", ""),
                content=r.get("body", ""),
            )
            for r in raw
        ]


__all__ = ["NewsClient"]


def _timelimit_from_dt(from_dt: datetime | None) -> str | None:
    """Convert a lower-bound datetime to a DDGS ``timelimit`` token.

    Args:
        from_dt: Optional start of the date window (UTC).

    Returns:
        One of ``"d"``, ``"w"``, ``"m"``, ``"y"``, or ``None`` when no
        time constraint should be applied.
    """
    if from_dt is None:
        return None
    days_ago = (datetime.utcnow() - from_dt.replace(tzinfo=None)).days
    if days_ago <= 1:
        return "d"
    if days_ago <= 7:
        return "w"
    if days_ago <= 31:
        return "m"
    return "y"


def _article_id(url: str | None, title: str) -> str:
    """Build a deterministic article ID from url and title."""
    key = f"{url or title}"
    return "ddgs-" + hashlib.sha256(key.encode()).hexdigest()[:16]


def _parse_ddgs_date(raw: str | None) -> datetime:
    """Parse a DDGS date string to a UTC-aware datetime.

    Args:
        raw: Raw date string from DDGS, e.g. ``"2026-05-24T10:30:00+00:00"``.

    Returns:
        UTC-aware :class:`datetime`, falling back to ``now`` on parse failure.
    """
    if not raw:
        return datetime.now(tz=timezone.utc)
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    return datetime.now(tz=timezone.utc)


__all__ = ["NewsClient"]
