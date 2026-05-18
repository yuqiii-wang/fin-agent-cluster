"""Resources — outbound data provider layer.

Sub-packages
------------
info   — DDGS-backed web search client + models
news   — news article client + models + mock transport
stats  — market statistics client + models + mock transport
"""

from __future__ import annotations

from backend.resources.info.client import InfoClient
from backend.resources.info.models import InfoResult
from backend.resources.news.client import NewsClient
from backend.resources.news.models import NewsArticle, NewsListResponse
from backend.resources.stats.client import StatsClient
from backend.resources.stats.models import StatsListResponse, StatsMatrix, StatsRecord

__all__ = [
    "InfoClient",
    "InfoResult",
    "NewsClient",
    "NewsArticle",
    "NewsListResponse",
    "StatsClient",
    "StatsListResponse",
    "StatsMatrix",
    "StatsRecord",
]
