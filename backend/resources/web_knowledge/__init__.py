"""Web-knowledge provider package.

Fetches raw HTML from well-known financial web pages (competitors, press
releases, option chain) for a given equity symbol via plain HTTP GET.

Sub-packages
------------
errors  — web-knowledge-specific error codes.

Exports
-------
WebKnowledgeClient  — async HTTP client.
WebPageType         — enum of supported page categories.
WebPageResponse     — Pydantic model for a fetched page result.

Reference URL patterns (populated dynamically per symbol)
----------------------------------------------------------
* competitors:     https://www.marketbeat.com/stocks/{EXCHANGE}/{SYMBOL}/competitors-and-alternatives/
* press_releases:  https://www.nasdaq.com/market-activity/stocks/{symbol}/press-releases
* option_chain:    https://www.nasdaq.com/market-activity/stocks/{symbol}/option-chain
"""

from __future__ import annotations

from backend.resources.web_knowledge.client import WebKnowledgeClient
from backend.resources.web_knowledge.models import WebPageResponse, WebPageType

__all__ = [
    "WebKnowledgeClient",
    "WebPageResponse",
    "WebPageType",
]