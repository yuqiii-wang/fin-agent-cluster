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
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.study_web_content import (
    StudyWebContentOutput,
)


class NavigateWebInput(BaseModel):
    """Input for the navigate_web TaskSeq pipeline.

    Attributes:
        url:               HTTP/HTTPS URL to crawl.
        objective:         Research question or goal that drives the crawl and LLM extraction.
        output_json_schema: JSON schema dict describing the expected structure of the
                            transform script's stdout JSON.  Forwarded to ``study_web_content``
                            so the LLM generates a script whose output conforms to the
                            downstream task's input (e.g. ``GetStatsInput``).
        additional_context: Extra instruction snippets forwarded to ``study_web_content`` and
                            appended to its system prompt.  Callers inject domain-specific
                            extraction rules here (e.g. peers node's COMPANY_MAP skill).
        max_links:         Maximum number of links to extract from the page for follow-up
                           candidate suggestions.  Defaults to 50.
    """

    url: str = Field(description="HTTP/HTTPS URL to crawl.")
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
        description="Maximum links to extract from the page.",
    )


class NavigateWebOutput(BaseModel):
    """Combined output from all four tasks in the navigate_web pipeline.

    Attributes:
        crawl_url:          Output from the ``crawl_url`` task.
        html_to_markdown:   Output from the ``html_to_markdown`` task.
        study_web_content:  Output from the ``study_web_content`` task (includes
                            ``source_markdown`` and ``transform_script``).
        run_sandbox:        Output from the ``run_sandbox`` task; ``stdout`` contains
                            the JSON produced by the transform script.
    """

    crawl_url: CrawlUrlOutput = Field(description="Crawl task output.")
    html_to_markdown: HtmlToMarkdownOutput = Field(description="HTML-to-Markdown conversion output.")
    study_web_content: StudyWebContentOutput = Field(description="LLM transform-script generation output.")
    run_sandbox: RunSandboxOutput = Field(description="Sandbox execution output; stdout holds the extracted JSON.")


__all__ = [
    "NavigateWebInput",
    "NavigateWebOutput",
]
