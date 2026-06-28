"""Pydantic models for the ARK (Volcano Engine / Doubao) web-search provider.

Exposes two logical responses used throughout the resources layer:

* :class:`ArkWebSearchResult`  — raw citations returned by the ARK web
  search tool (title / URL / snippet / optional metadata).
* :class:`ArkSearchSummaryResponse`  — the summarised textual answer
  together with the citations that produced it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ArkWebSearchResult(BaseModel):
    """A single citation / search result returned by the ARK web-search tool.

    This normalises the various shapes that Doubao emits inside the
    ``tool_calls`` payload into a uniform record: ``title`` + ``url`` +
    ``snippet`` plus optional metadata such as publication date or source
    category.
    """

    title: str = Field(default="", description="Title of the matched web page.")
    url: str = Field(default="", description="Canonical URL of the matched page.")
    snippet: str = Field(default="", description="Short snippet / excerpt shown to the model.")
    source_category: str | None = Field(
        default=None,
        description="Optional provider-specific category, e.g. ``news``, ``toutiao``, ``douyin``.",
    )
    published_at: datetime | None = Field(
        default=None,
        description="Optional publication timestamp (UTC).  Filled in when the provider returns a parseable date.",
    )
    raw: dict[str, Any] | None = Field(
        default=None,
        description="The raw provider-specific record, kept for diagnostics.",
    )


class ArkSearchSummaryResponse(BaseModel):
    """Response returned by :meth:`ArkWebSearchClient.search_and_summary`.

    Combines a summary answer with the list of citations used to ground it.
    """

    answer: str = Field(
        description="Summarised textual answer produced by the Doubao model after searching the web.",
    )
    results: list[ArkWebSearchResult] = Field(
        default_factory=list,
        description="Citations / raw web-search results the model used to build the answer.",
    )
    provider: str = Field(
        default="ark",
        description="Always ``ark`` — used by callers to route diagnostics.",
    )
    raw: dict[str, Any] | None = Field(
        default=None,
        description="The raw provider response body, kept for debugging.",
    )

    def to_web_page_results(self) -> list[dict[str, Any]]:
        """Convert this summary to the list-of-dicts shape accepted by
        :meth:`backend.resources.web_knowledge.models.WebPageResponse.for_web_search`.

        Each element has the keys ``title``, ``url``, ``snippet``, and
        optional ``source_category``, ``published_at`` and ``raw``.
        """
        out: list[dict[str, Any]] = []
        for r in self.results:
            record = {
                "title": r.title,
                "url": r.url,
                "snippet": r.snippet,
            }
            if r.source_category:
                record["source_category"] = r.source_category
            if r.published_at is not None:
                record["published_at"] = r.published_at.isoformat()
            if r.raw:
                record["raw"] = r.raw
            out.append(record)
        return out
