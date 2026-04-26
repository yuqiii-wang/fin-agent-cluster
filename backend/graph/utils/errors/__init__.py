"""Graph utilities error code registry package.

Re-exports all error code constants and the ``GRAPH_UTILS_ERRORS`` description dict::

    from backend.graph.utils.errors import (
        GRAPH_UTILS_ERRORS,
        UTIL_NEWS_ENRICHMENT_FAILED,
        UTIL_PDF_FETCH_FAILED,
        UTIL_EMBED_FAILED,
    )
"""

from __future__ import annotations

from backend.graph.utils.errors.codes import (
    GRAPH_UTILS_ERRORS,
    UTIL_NEWS_ENRICHMENT_FAILED,
    UTIL_PDF_FETCH_FAILED,
    UTIL_EMBED_FAILED,
)

__all__ = [
    "GRAPH_UTILS_ERRORS",
    "UTIL_NEWS_ENRICHMENT_FAILED",
    "UTIL_PDF_FETCH_FAILED",
    "UTIL_EMBED_FAILED",
]
