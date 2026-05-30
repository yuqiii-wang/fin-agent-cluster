"""Shared input/output models for the load_md_from_url TaskSeq."""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.langgraph.models.common_tasks.task_seqs.navigate_web.load_markdown_from_url.crawl_url import (
    CrawlUrlOutput,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.load_markdown_from_url.html_to_markdown import (
    HtmlToMarkdownOutput,
)


class LoadMdFromUrlInput(BaseModel):
    """Input for the load_md_from_url TaskSeq pipeline.

    Attributes:
        url:       HTTP/HTTPS URL to crawl.
        objective: Research question used in LLM orchestration fallback on crawl failure.
        max_links: Maximum number of links to extract from the page.
    """

    url: str = Field(description="HTTP/HTTPS URL to crawl.")
    objective: str = Field(
        description="Research objective used in LLM orchestration fallback.",
    )
    max_links: int = Field(
        default=50,
        ge=0,
        le=500,
        description="Maximum links to extract from the page.",
    )


class LoadMdFromUrlOutput(BaseModel):
    """Combined output from crawl_url and html_to_markdown.

    Attributes:
        crawl_url:        Output from the ``crawl_url`` task.
        html_to_markdown: Output from the ``html_to_markdown`` task.
    """

    crawl_url: CrawlUrlOutput = Field(description="Crawl task output.")
    html_to_markdown: HtmlToMarkdownOutput = Field(
        description="HTML-to-Markdown conversion output.",
    )


__all__ = [
    "LoadMdFromUrlInput",
    "LoadMdFromUrlOutput",
]
