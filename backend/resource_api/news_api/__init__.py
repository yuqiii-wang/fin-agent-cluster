"""News API — unified models, providers, and cached client."""

from backend.resource_api.news_api.models import (
    NewsArticle,
    NewsMethod,
    NewsQuery,
    NewsResult,
    NewsSource,
)
from backend.resource_api.news_api.client import NewsClient

__all__ = [
    "NewsArticle",
    "NewsClient",
    "NewsMethod",
    "NewsQuery",
    "NewsResult",
    "NewsSource",
]
