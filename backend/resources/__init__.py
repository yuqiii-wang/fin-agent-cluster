"""Resources — outbound data provider layer.

Sub-packages
------------
news   — news article client + models + mock transport
stats  — market statistics client + models + mock transport
"""

from __future__ import annotations

from backend.resources.news.client import NewsClient
from backend.resources.news.models import NewsArticle, NewsListResponse
from backend.resources.stats.client import StatsClient
from backend.resources.stats.models import StatsListResponse, StatsMatrix, StatsRecord

__all__ = [
    "NewsClient",
    "NewsArticle",
    "NewsListResponse",
    "StatsClient",
    "StatsListResponse",
    "StatsMatrix",
    "StatsRecord",
]
