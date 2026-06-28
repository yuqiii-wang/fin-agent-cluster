"""Pydantic models for the web-knowledge sub-API.

This module exposes two primary data structures:

* :class:`WebPageType`  — the set of categories of content the client
  knows how to fetch (competitors / press releases / option chain / analyst
  estimates / AI-driven web search).
* :class:`WebPageResponse`  — the returned record produced by
  :meth:`WebKnowledgeClient.fetch`.

The ``web_search`` page type delegates to the
:mod:`backend.resources.web_knowledge.providers.ark` sub-package, which
wraps the Doubao ``web_search`` tool.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from enum import Enum

from pydantic import BaseModel, Field


class WebPageType(str, Enum):
    """Supported page types for web-knowledge fetches / searches.

    The first four categories resolve to a known domain URL
    (see :mod:`backend.resources.web_knowledge.urls`).  ``web_search``
    is an AI-driven search-and-summarise call backed by the Doubao
    ``web_search`` tool.
    """

    competitors = "competitors"
    press_releases = "press_releases"
    option_chain = "option_chain"
    estimate = "estimate"
    web_search = "web_search"


class WebPageResponse(BaseModel):
    """Fetched web page result, or the result of an AI-driven web search.

    Fields are intentionally flexible:

    * For a plain page-type fetches (``competitors``, ``press_releases``,
      ``option_chain``, ``estimate``) ``symbol``, ``url``, and
      ``html`` are always populated; ``page_type`` identifies the category.
    * For ``page_type == 'web_search'`` ``query`` is the original
      query string; ``answer`` is the Doubao-generated summary;
      ``results`` is the list of normalised citations the model used
      to build the answer; ``html`` is empty and ``exchange`` is
      ``None``.
    """

    symbol: str = Field(default="", description="Equity symbol, e.g. 'AAPL'. Empty string for web_search calls.")
    exchange: str | None = Field(default=None, description="Exchange the symbol is listed on, e.g. 'NASDAQ'. None for web_search.")
    page_type: WebPageType = Field(..., description="The category of web page that was fetched / queried.")
    url: str = Field(default="", description="Canonical URL that was fetched, or the ARK endpoint for web_search.")
    html: str = Field(default="", description="Raw HTML content of the fetched page. Empty for web_search.")

    query: str | None = Field(default=None, description="The original query string (only set for web_search).")
    answer: str | None = Field(default=None, description="AI-generated summary answer (only set for web_search).")
    results: list[dict[str, Any]] | None = Field(
        default=None,
        description="Normalised citations / search results (only set for web_search).",
    )
    published_at: datetime | None = Field(
        default=None,
        description="Optional publication timestamp for the web-search response (UTC).",
    )
    raw: dict[str, Any] | None = Field(
        default=None,
        description="Optional raw provider payload, kept for diagnostics.",
    )

    @staticmethod
    def for_web_search(
        query: str,
        answer: str,
        results: list[dict[str, Any]] | None = None,
        *,
        url: str = "https://ark.cn-beijing.volces.com/api/v3/responses",
        raw: dict[str, Any] | None = None,
        published_at: datetime | None = None,
    ) -> "WebPageResponse":
        """Factory for ``page_type=web_search`` responses.

        Args:
            query:   Original user query.
            answer:  Textual summary provided by the Doubao ``web_search`` tool.
            results: List of normalised citations (dicts).  Use
                     :meth:`ArkSearchSummaryResponse.results` via
                     :meth:`ArkSearchSummaryResponse.to_web_page_results` to
                     obtain a list of dicts from the provider-specific data
                     class.
            url:     The ARK endpoint that produced the answer.
            raw:     Optional raw provider payload.
            published_at: Optional UTC timestamp for the response.
        """
        return WebPageResponse(
            symbol="",
            exchange=None,
            page_type=WebPageType.web_search,
            url=url,
            html="",
            query=query,
            answer=answer,
            results=results or [],
            published_at=published_at,
            raw=raw,
        )
