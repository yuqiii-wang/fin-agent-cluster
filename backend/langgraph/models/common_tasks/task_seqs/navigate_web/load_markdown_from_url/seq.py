"""load_md_from_url -- TaskSeq: fetch a URL and convert its HTML to Markdown.

Orchestration
-------------
1. ``crawl_url``        -- httpx async fetch + link extraction.
2. ``html_to_markdown`` -- markitdown HTML -> Markdown conversion.

Failures propagate to the caller.  Recovery (if any) is owned by the hosting
AGENT node's step loop via ``llm_orchestration_on_failure`` -- this sequence
performs no per-task orchestration of its own.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from backend.langgraph.models.common_tasks.task_seqs.navigate_web.load_markdown_from_url.crawl_url import (
    CrawlUrlInput,
    CrawlUrlOutput,
    crawl_url,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.load_markdown_from_url.html_to_markdown import (
    HtmlToMarkdownInput,
    html_to_markdown,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.load_markdown_from_url.models import (
    LoadMdFromUrlInput,
    LoadMdFromUrlOutput,
)
from backend.langgraph.models.models import NodeContext
from backend.langgraph.models.task_seq import TaskSeq

logger = logging.getLogger(__name__)

_SEQ_NAME = "load_md_from_url"


async def _pipeline(
    run_task_fn: Callable[..., Awaitable[Any]],
    ctx: NodeContext,
    seq_input: LoadMdFromUrlInput,
) -> LoadMdFromUrlOutput:
    """Run crawl_url -> html_to_markdown.

    Args:
        run_task_fn: Bound ``self.run_task`` from the hosting node.
        ctx:         Current node context.
        seq_input:   Typed pipeline input.

    Returns:
        Combined output from crawl_url and html_to_markdown.
    """
    crawl_result = await run_task_fn(
        crawl_url,
        ctx,
        CrawlUrlInput(url=seq_input.url, max_links=seq_input.max_links),
    )
    crawl_out: CrawlUrlOutput = crawl_result.content

    md_result = await run_task_fn(
        html_to_markdown,
        ctx,
        HtmlToMarkdownInput(
            raw_html=crawl_out.raw_html,
            source_url=crawl_out.url,
        ),
    )

    return LoadMdFromUrlOutput(
        crawl_url=crawl_out,
        html_to_markdown=md_result.content,
    )


load_md_from_url: TaskSeq[LoadMdFromUrlInput, LoadMdFromUrlOutput] = TaskSeq(
    name=_SEQ_NAME,
    description=(
        "Sequential pipeline: fetch a web page (crawl_url) and convert its HTML body to "
        "Markdown (html_to_markdown).  Failures propagate to the caller."
    ),
    tasks=[crawl_url, html_to_markdown],
    input_type=LoadMdFromUrlInput,
    output_type=LoadMdFromUrlOutput,
    pipeline_fn=_pipeline,
)

__all__ = [
    "load_md_from_url",
    "LoadMdFromUrlInput",
    "LoadMdFromUrlOutput",
]
