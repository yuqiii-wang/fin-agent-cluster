"""Web-knowledge provider package.

Fetches raw HTML from well-known financial web pages (competitors, press
releases, option chain, analyst estimates) for a given equity symbol via
plain HTTP GET.  Also exposes an AI-driven web-search + summary client
backed by the Doubao ``web_search`` tool — see
:mod:`backend.resources.web_knowledge.providers.ark`.

Sub-packages
------------
errors     -- web-knowledge-specific error codes (``WK_*`` + ``ARK_*``).
providers  -- provider-specific clients (currently ARK web-search).

Exports
-------
WebKnowledgeClient  -- async HTTP client (fetch + search_and_summary).
WebPageType         -- enum of supported page categories.
WebPageResponse     -- Pydantic model for a fetched page or AI search result.

Reference URL patterns (populated dynamically per symbol)
----------------------------------------------------------
* competitors:     https://www.marketbeat.com/stocks/{EXCHANGE}/{SYMBOL}/competitors-and-alternatives/
* press_releases:  https://www.nasdaq.com/market-activity/stocks/{symbol}/press-releases
* option_chain:    https://www.nasdaq.com/market-activity/stocks/{symbol}/option-chain
* estimate:        https://finance.yahoo.com/quote/{SYMBOL}/analysis/
* web_search:      https://ark.cn-beijing.volces.com/api/v3/chat/completions  (Doubao ``web_search`` tool)
"""

from __future__ import annotations

from backend.resources.web_knowledge.client import WebKnowledgeClient
from backend.resources.web_knowledge.models import WebPageResponse, WebPageType

__all__ = [
    "WebKnowledgeClient",
    "WebPageResponse",
    "WebPageType",
]
