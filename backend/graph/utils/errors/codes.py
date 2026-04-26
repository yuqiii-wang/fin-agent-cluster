"""Graph utilities error code registry.

These codes identify non-fatal failures in the utility helpers that
are swallowed and logged; callers receive partial or empty results.

Error code prefixes
-------------------
``UTIL_``   — Graph utility layer failures.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Error code constants
# ---------------------------------------------------------------------------

#: LLM enrichment step on news articles failed; proceeding without enrichment.
UTIL_NEWS_ENRICHMENT_FAILED = "UTIL_NEWS_ENRICHMENT_FAILED"

#: Fetching or parsing a PDF from a URL failed; article is skipped.
UTIL_PDF_FETCH_FAILED = "UTIL_PDF_FETCH_FAILED"

#: Embedding a news article failed; article stored without vector.
UTIL_EMBED_FAILED = "UTIL_EMBED_FAILED"

# ---------------------------------------------------------------------------
# Description registry
# ---------------------------------------------------------------------------

#: Maps each utility error code to a human-readable description.
GRAPH_UTILS_ERRORS: dict[str, str] = {
    UTIL_NEWS_ENRICHMENT_FAILED: (
        "LLM enrichment of news articles failed. "
        "Articles are stored without sentiment/entity annotations."
    ),
    UTIL_PDF_FETCH_FAILED: (
        "Fetching or parsing a PDF document failed. "
        "The article will be processed without PDF content."
    ),
    UTIL_EMBED_FAILED: (
        "Generating an embedding vector for a news article failed. "
        "The article is stored but will not be returned by vector similarity search."
    ),
}
