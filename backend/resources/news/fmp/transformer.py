"""FMP (Financial Modeling Prep) news transformer.

Converts the FMP ``/stable/news`` JSON payload into
:class:`~backend.resources.news.models.NewsArticle` instances.

FMP stable endpoint response shape
-----------------------------------
::

    [
        {
            "symbol":        "AAPL",
            "publishedDate": "2026-05-24T10:30:00.000Z",
            "title":         "Apple Reports Strong Q2...",
            "text":          "Full article body...",
            "url":           "https://...",
            "site":          "The Motley Fool",
        },
        ...
    ]
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from backend.resources.news.models import NewsArticle

_SOURCE_LABEL = "fmp"


def _parse_dt(raw: str | None) -> datetime:
    """Parse an FMP ``publishedDate`` string into a timezone-aware datetime.

    Args:
        raw: Raw date string from the FMP response.

    Returns:
        UTC-aware :class:`datetime`.
    """
    if not raw:
        return datetime.now(tz=timezone.utc)
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(tz=timezone.utc)


def _article_id(url: str | None, title: str, published_raw: str | None) -> str:
    """Build a deterministic article ID from url + title + date."""
    key = f"{url or title}|{published_raw or ''}"
    return "fmp-" + hashlib.sha256(key.encode()).hexdigest()[:16]


def transform(raw_items: list[dict]) -> list[NewsArticle]:
    """Convert a list of FMP news dicts into :class:`NewsArticle` objects.

    Args:
        raw_items: Parsed JSON list from the FMP ``/stable/news`` response.

    Returns:
        List of :class:`NewsArticle` instances.
    """
    articles: list[NewsArticle] = []
    for r in raw_items:
        published_raw = r.get("publishedDate")
        articles.append(
            NewsArticle(
                id=_article_id(r.get("url"), r.get("title", ""), published_raw),
                symbol=r.get("symbol"),
                title=r.get("title", ""),
                source=_SOURCE_LABEL,
                source_name=r.get("site"),
                published_at=_parse_dt(published_raw),
                content=r.get("text", ""),
                url=r.get("url"),
            )
        )
    return articles
