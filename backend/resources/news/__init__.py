"""News provider package.

Provides news article and web-search models, and the DDGS-backed client.

Sub-packages
------------
errors  — news-specific error codes.

Exports
-------
NewsClient       — DDGS-backed async client.
NewsArticle      — Pydantic model for a single article.
NewsListResponse — Pydantic model for a paginated list.
InfoResult       — Pydantic model for a web-search result.
"""

from __future__ import annotations

from backend.resources.news.client import NewsClient
from backend.resources.news.models import InfoResult, NewsArticle, NewsListResponse

__all__ = ["NewsClient", "NewsArticle", "NewsListResponse", "InfoResult"]
