"""Shared input/output models for the navigate_web TaskSeq pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.langgraph.models.common_tasks.run_sandbox import RunSandboxOutput
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.load_markdown_from_url.crawl_url import (
    CrawlUrlOutput,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.load_markdown_from_url.html_to_markdown import (
    HtmlToMarkdownOutput,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.propose_web_knowledge_urls import (
    ProposeWebKnowledgeUrlsOutput,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.study_web_content import (
    StudyWebContentOutput,
)


class NavigateWebInput(BaseModel):
    """Input for the navigate_web TaskSeq pipeline.

    Attributes:
        symbol:            Equity ticker symbol used by ``propose_web_knowledge_urls``
                           to construct the Yahoo Finance options URL.
        objective:         Research question or goal that drives the crawl and LLM extraction.
        output_json_schema: JSON schema dict describing the expected structure of the
                            transform script's stdout JSON.  Forwarded to ``study_web_content``
                            so the LLM generates a script whose output conforms to the
                            downstream task's input (e.g. ``GetStatsInput``).
        additional_context: Extra instruction snippets forwarded to ``study_web_content`` and
                            appended to its system prompt.  Callers inject domain-specific
                            extraction rules here (e.g. peers node's COMPANY_MAP skill).
        max_links:         Maximum number of links to extract from each page for follow-up
                           candidate suggestions.  Defaults to 50.
    """

    symbol: str = Field(description="Equity ticker symbol to propose the Yahoo Finance options URL for.")
    objective: str = Field(description="Research objective for the LLM content extraction.")
    output_json_schema: dict = Field(
        description="JSON schema for the transform script's stdout JSON.",
    )
    additional_context: list[str] = Field(
        default_factory=list,
        description="Extra instruction snippets forwarded to study_web_content's system prompt.",
    )
    max_links: int = Field(
        default=50,
        ge=0,
        le=500,
        description="Maximum links to extract from each page.",
    )


class NavigateWebPerUrlOutput(BaseModel):
    """Combined output from one URL's pipeline run within navigate_web.

    Attributes:
        crawl_url:          Output from the ``crawl_url`` task for this URL.
        html_to_markdown:   Output from the ``html_to_markdown`` task.
        study_web_content:  Output from the ``study_web_content`` task.
        run_sandbox:        Output from the ``run_sandbox`` task; ``stdout`` contains
                            the JSON produced by the transform script.
    """

    crawl_url: CrawlUrlOutput = Field(description="Crawl task output.")
    html_to_markdown: HtmlToMarkdownOutput = Field(description="HTML-to-Markdown conversion output.")
    study_web_content: StudyWebContentOutput = Field(description="LLM transform-script generation output.")
    run_sandbox: RunSandboxOutput = Field(description="Sandbox execution output; stdout holds the extracted JSON.")


class NavigateWebOutput(BaseModel):
    """Combined output from the navigate_web pipeline.

    Attributes:
        propose_web_knowledge_urls: Output from the URL proposal step.
        results:                    Per-URL pipeline results, one entry per URL
                                    returned by ``propose_web_knowledge_urls``.
                                    Entries for URLs that failed are omitted; an
                                    empty list means all URLs failed.
    """

    propose_web_knowledge_urls: ProposeWebKnowledgeUrlsOutput = Field(
        description="URL proposal task output.",
    )
    results: list[NavigateWebPerUrlOutput] = Field(
        description="Per-URL crawl + extract results, run in parallel.",
    )


__all__ = [
    "NavigateWebInput",
    "NavigateWebPerUrlOutput",
    "NavigateWebOutput",
]
