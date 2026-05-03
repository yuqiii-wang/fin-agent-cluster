"""News provider package.

Provides news article models, mock data, and the httpx client.

Sub-packages
------------
mock    — in-process mock transport + static articles for offline / test use.
errors  — news-specific error codes.

Exports
-------
NewsClient       — Async httpx client (mock provider by default).
NewsArticle      — Pydantic model for a single article.
NewsListResponse — Pydantic model for a paginated list.
"""

from __future__ import annotations

from backend.resources.news.client import NewsClient
from backend.resources.news.models import NewsArticle, NewsListResponse

__all__ = ["NewsClient", "NewsArticle", "NewsListResponse"]
