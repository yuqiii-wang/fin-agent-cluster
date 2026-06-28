"""ARK (Volcano Engine / Doubao) web-search provider sub-package.

Wraps the Doubao ``web_search`` tool so the surrounding
:mod:`backend.resources.web_knowledge` layer can dispatch to it
transparently when a caller asks for the ``web_search`` page type or
calls :meth:`WebKnowledgeClient.search_and_summary` directly.

Sub-packages
------------
errors  -- ARK-specific error codes.

Exports
-------
ArkWebSearchClient        -- async HTTP client for the ``web_search`` tool.
ArkWebSearchResult        -- Pydantic model for a single search citation.
ArkSearchSummaryResponse  -- Pydantic model for the ``(answer, citations)`` response.
"""

from __future__ import annotations

from backend.resources.web_knowledge.providers.ark.client import ArkWebSearchClient
from backend.resources.web_knowledge.providers.ark.models import (
    ArkSearchSummaryResponse,
    ArkWebSearchResult,
)

__all__ = [
    "ArkWebSearchClient",
    "ArkWebSearchResult",
    "ArkSearchSummaryResponse",
]
