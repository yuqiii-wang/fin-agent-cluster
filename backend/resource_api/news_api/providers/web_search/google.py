"""Google Custom Search API backend.

Uses the JSON/Atom Custom Search API:
https://developers.google.com/custom-search/v1/reference/rest/v1/cse/list

Requires a Custom Search Engine (CSE) configured to search the entire web:
  GOOGLE_CSE_API_KEY  — API key from Google Cloud Console
  GOOGLE_CSE_CX       — Search engine ID from https://cse.google.com
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from backend.config import get_settings
from backend.resource_api.exceptions import ProviderNotFoundError
from backend.resource_api.news_api.models import NewsArticle, NewsQuery, NewsResult

logger = logging.getLogger(__name__)

_ENDPOINT = "https://www.googleapis.com/customsearch/v1"


def is_configured() -> bool:
    """Return True when both GOOGLE_CSE_API_KEY and GOOGLE_CSE_CX are present."""
    s = get_settings()
    return bool(s.GOOGLE_CSE_API_KEY and s.GOOGLE_CSE_CX)


async def fetch(query: NewsQuery) -> NewsResult:
    """Fetch news via Google Custom Search API.

    Google CSE does not have a dedicated news endpoint; results are filtered
    by ``dateRestrict=d7`` (last 7 days) and sorted by date to surface recent
    articles.

    Args:
        query: Structured news query.

    Returns:
        Normalised :class:`~app.resource_api.news_api.models.NewsResult`.

    Raises:
        ValueError: When API key or CX is not configured.
        httpx.HTTPStatusError: On non-2xx API responses.
    """
    s = get_settings()
    if not s.GOOGLE_CSE_API_KEY or not s.GOOGLE_CSE_CX:
        raise ValueError("GOOGLE_CSE_API_KEY and GOOGLE_CSE_CX must both be configured")

    # Google CSE returns max 10 per request; cap at 10
    limit = min(int(query.params.get("limit", 10)), 10)

    if query.method == "company_news" and query.symbol:
        q_text = f"{query.symbol.upper()} stock news"
    elif query.method == "topic_news" and query.query:
        q_text = query.query
    else:
        raise ValueError("google provider requires symbol (company_news) or query (topic_news)")

    params = {
        "key": s.GOOGLE_CSE_API_KEY,
        "cx": s.GOOGLE_CSE_CX,
        "q": q_text,
        "num": str(limit),
        "dateRestrict": "d7",   # last 7 days
        "sort": "date",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(_ENDPOINT, params=params)
    if resp.status_code == 404:
        raise ProviderNotFoundError("google_cse", "Google Custom Search API", q_text, "HTTP 404 Not Found")
    resp.raise_for_status()
    data = resp.json()

    raw_items = data.get("items", [])
    logger.debug("[google_cse] query=%r returned %d results", q_text, len(raw_items))

    articles = []
    for item in raw_items:
        # Page-map snippet may contain a timestamp
        pagemap = item.get("pagemap", {})
        metatags = (pagemap.get("metatags") or [{}])[0]
        published_at: str | None = (
            metatags.get("article:published_time")
            or metatags.get("og:updated_time")
            or None
        )
        if published_at:
            try:
                dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                published_at = dt.isoformat()
            except ValueError:
                pass

        source_name = item.get("displayLink", "google")

        articles.append(
            NewsArticle(
                title=item.get("title", ""),
                url=item.get("link"),
                source_name=source_name,
                published_at=published_at,
                summary=item.get("snippet"),
            )
        )

    return NewsResult(
        method=query.method,
        source="web_search",
        symbol=query.symbol,
        query=query.query,
        articles=articles,
        fetched_at=datetime.now(timezone.utc),
    )
