"""Resources -- outbound data provider layer.

Sub-packages
------------
news          -- DDGS-backed news and web-search client + models
stats         -- market statistics client + models + mock transport
web_knowledge -- raw HTML fetcher for financial web pages (competitors, press releases, options)
"""

from __future__ import annotations

from backend.resources.news.client import NewsClient
from backend.resources.news.models import InfoResult, NewsArticle, NewsListResponse
from backend.resources.stats.client import StatsClient
from backend.resources.stats.models import OhlcvStatsMatrix, StatsListResponse, StatsRecord
from backend.resources.web_knowledge.client import WebKnowledgeClient
from backend.resources.web_knowledge.models import WebPageResponse, WebPageType

__all__ = [
    "NewsClient",
    "InfoResult",
    "NewsArticle",
    "NewsListResponse",
    "StatsClient",
    "StatsListResponse",
    "OhlcvStatsMatrix",
    "StatsRecord",
    "WebKnowledgeClient",
    "WebPageResponse",
    "WebPageType",
]
