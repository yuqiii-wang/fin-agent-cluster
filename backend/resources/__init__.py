"""Resources — outbound data provider layer.

Sub-packages
------------
news   — DDGS-backed news and web-search client + models
stats  — market statistics client + models + mock transport
"""

from __future__ import annotations

from backend.resources.news.client import NewsClient
from backend.resources.news.models import InfoResult, NewsArticle, NewsListResponse
from backend.resources.stats.client import StatsClient
from backend.resources.stats.models import StatsListResponse, StatsMatrix, StatsRecord

__all__ = [
    "NewsClient",
    "InfoResult",
    "NewsArticle",
    "NewsListResponse",
    "StatsClient",
    "StatsListResponse",
    "StatsMatrix",
    "StatsRecord",
]
