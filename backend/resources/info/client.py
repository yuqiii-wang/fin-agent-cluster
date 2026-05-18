"""DDGS-backed web-search client for backend.resources.info."""

from __future__ import annotations

import asyncio
import logging

from ddgs import DDGS

from backend.resources.info.errors import INFO_NO_RESULTS, INFO_SEARCH_FAILED
from backend.resources.info.models import InfoResult

__all__ = ["InfoClient"]

_MAX_CONTENT_CHARS = 2000
logger = logging.getLogger(__name__)


class InfoClient:
    """Async wrapper around the synchronous DDGS text-search API.

    Uses ``asyncio.get_event_loop().run_in_executor`` so that the blocking
    DuckDuckGo HTTP call does not block the event loop.
    """

    async def search(self, query: str, max_results: int = 3) -> list[InfoResult]:
        """Search the web and return up to *max_results* results.

        Args:
            query:       Free-form search query.
            max_results: Maximum number of results to return.

        Returns:
            List of :class:`InfoResult` objects, possibly empty on failure.
        """
        loop = asyncio.get_event_loop()
        try:
            raw: list[dict] = await loop.run_in_executor(
                None,
                lambda: list(DDGS().text(query, max_results=max_results)),
            )
        except Exception as exc:
            logger.error("[%s] DDGS search failed query=%r: %s", INFO_SEARCH_FAILED, query, exc)
            return []

        if not raw:
            logger.error("[%s] DDGS returned no results for query=%r", INFO_NO_RESULTS, query)
            return []

        return [
            InfoResult(
                url=r.get("href", ""),
                title=r.get("title", ""),
                content=r.get("body", "")[:_MAX_CONTENT_CHARS],
            )
            for r in raw
        ]
