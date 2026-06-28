"""Web-knowledge HTTP client.

This module wraps two kinds of outbound requests:

* Plain HTML page fetches for :class:`WebPageType` categories such as
  ``competitors``, ``press_releases``, ``option_chain``, and ``estimate``.
  Each of those resolves to a specific URL through
  :mod:`backend.resources.web_knowledge.urls`.
* AI-driven web search and summary through the Doubao ``web_search`` tool
  via :class:`ArkWebSearchClient` (defined in
  :mod:`backend.resources.web_knowledge.providers.ark`).  The original
  implementation in this codebase lives in that sub-package; this module
  re-exports it as :meth:`WebKnowledgeClient.search_and_summary` so the
  rest of the application has a single entry point.

Typical usage::

    from backend.resources.web_knowledge.client import WebKnowledgeClient
    from backend.resources.web_knowledge.models import WebPageType

    client = WebKnowledgeClient()
    # Plain HTML page fetch
    response = await client.fetch("AAPL", WebPageType.competitors, exchange="NASDAQ")
    print(response.url, len(response.html))

    # AI web search
    summary = await client.search_and_summary("AAPL latest earnings call summary")
    print(summary.answer)
    print(summary.results)

    await client.aclose()
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from _shared.httpx_client import HTTPStatusError, RequestError, make_web_browser_async_client
from backend.resources.web_knowledge.errors import WK_FETCH_FAILED
from backend.resources.web_knowledge.models import WebPageResponse, WebPageType
from backend.resources.web_knowledge.providers.ark.client import ArkWebSearchClient
from backend.resources.web_knowledge.providers.ark.models import (
    ArkSearchSummaryResponse,
    ArkWebSearchResult,
)
from backend.resources.web_knowledge.urls import build_url

logger = logging.getLogger(__name__)


class WebKnowledgeClient:
    """Async HTTP client for web-knowledge page fetches and AI-driven web searches.

    The client lazily initialises an :class:`ArkWebSearchClient` the first
    time a ``web_search`` call is issued.  The browser HTTP client is used
    for plain HTML page fetches.
    """

    def __init__(self) -> None:
        """Initialise the shared HTTP clients."""
        self._http = make_web_browser_async_client()
        self._ark: ArkWebSearchClient | None = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ark_client(self) -> ArkWebSearchClient:
        """Return a (lazily initialised) :class:`ArkWebSearchClient`."""
        if self._ark is None:
            self._ark = ArkWebSearchClient()
        return self._ark

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def fetch(
        self,
        symbol: str,
        page_type: WebPageType,
        exchange: str | None = None,
    ) -> WebPageResponse:
        """Fetch a known page for ``symbol`` and ``page_type``.

        When ``page_type`` is ``WebPageType.web_search`` the method
        transparently delegates to :meth:`_fetch_web_search` — the ARK
        web-search tool — rather than performing a GET request.

        Args:
            symbol:   Equity ticker symbol, e.g. ``'AAPL'``.  For
                      ``web_search`` this should be ``""``.
            page_type: One of :class:`WebPageType`.
            exchange: Only required for ``competitors``.

        Returns:
            :class:`WebPageResponse` wrapping the page content or the AI
            search answer + citations.

        Raises:
            RuntimeError: When the HTTP fetch fails or the response body is empty.
            ValueError:     When the underlying ARK call fails (e.g. missing
                            credentials or unsupported page_type).
        """
        if page_type == WebPageType.web_search:
            return await self._fetch_web_search(symbol)

        url = build_url(page_type, symbol, exchange)
        try:
            response = await self._http.get(url)
            response.raise_for_status()
        except HTTPStatusError as exc:
            logger.error(
                "[%s] HTTP %s fetching %s: %s",
                WK_FETCH_FAILED,
                exc.response.status_code,
                url,
                exc,
            )
            raise RuntimeError(
                f"[{WK_FETCH_FAILED}] HTTP {exc.response.status_code} fetching {url}"
            ) from exc
        except RequestError as exc:
            logger.error("[%s] Network error fetching %s: %s", WK_FETCH_FAILED, url, exc)
            raise RuntimeError(f"[{WK_FETCH_FAILED}] Network error fetching {url}") from exc

        html = response.text
        if not html.strip():
            logger.error("[%s] Empty response body from %s", WK_FETCH_FAILED, url)
            raise RuntimeError(f"[{WK_FETCH_FAILED}] Empty response body from {url}")

        return WebPageResponse(
            symbol=symbol.upper(),
            exchange=exchange.upper() if exchange else None,
            page_type=page_type,
            url=url,
            html=html,
        )

    async def _fetch_web_search(self, query: str) -> WebPageResponse:
        """Delegate to :class:`ArkWebSearchClient` and wrap in :class:`WebPageResponse`."""
        ark = self._ark_client()
        summary: ArkSearchSummaryResponse = await ark.search_and_summary(query)
        results = [
            _citation_to_dict(r) for r in (summary.results or [])
        ]
        return WebPageResponse(
            symbol="",
            exchange=None,
            page_type=WebPageType.web_search,
            url=ark.base_url,
            html="",
            query=query,
            answer=summary.answer,
            results=results,
            published_at=datetime.now(tz=timezone.utc),
            raw=summary.raw,
        )

    async def search_and_summary(
        self,
        query: str,
        *,
        system_prompt: str | None = None,
    ) -> ArkSearchSummaryResponse:
        """Run an ARK Doubao web search + AI summary call.

        Args:
            query:         Free-form query string in any language.
            system_prompt: Optional override for the Doubao system prompt.

        Returns:
            :class:`ArkSearchSummaryResponse` with the summarised answer
            and normalised citations.

        Raises:
            ValueError: When the client is misconfigured, the query is empty,
                        or the endpoint rejected the request.
        """
        ark = self._ark_client()
        return await ark.search_and_summary(query, system_prompt=system_prompt)

    async def aclose(self) -> None:
        """Close the underlying HTTP clients."""
        await self._http.aclose()
        if self._ark is not None:
            await self._ark.aclose()


def _citation_to_dict(result: ArkWebSearchResult) -> dict[str, Any]:
    """Convert an :class:`ArkWebSearchResult` to a plain ``dict`` for :class:`WebPageResponse`."""
    return {
        "title": result.title or "",
        "url": result.url or "",
        "snippet": result.snippet or "",
        "source_category": result.source_category,
        "published_at": result.published_at.isoformat() if result.published_at else None,
        "raw": result.raw,
    }


__all__ = ["WebKnowledgeClient"]
