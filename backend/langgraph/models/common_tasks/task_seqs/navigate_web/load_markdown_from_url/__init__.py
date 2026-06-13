"""load_markdown_from_url -- NodeTasks and TaskSeq for URL fetching and Markdown conversion.

Orchestration
-------------
1. ``crawl_url``        -- httpx async fetch + link extraction.
2. ``html_to_markdown`` -- markitdown HTML -> Markdown conversion.

On ``crawl_url`` failure, ``llm_orchestration_on_failure`` is invoked to decide recovery:
re-run ``propose_web_knowledge_urls`` with a new symbol, or propagate failure.
"""

from backend.langgraph.models.common_tasks.task_seqs.navigate_web.load_markdown_from_url.crawl_url import (
    CrawlUrlInput,
    CrawlUrlOutput,
    crawl_url,
    HANDLERS as _CU_HANDLERS,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.load_markdown_from_url.html_to_markdown import (
    HtmlToMarkdownInput,
    HtmlToMarkdownOutput,
    html_to_markdown,
    HANDLERS as _HTM_HANDLERS,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.load_markdown_from_url.models import (
    LoadMdFromUrlInput,
    LoadMdFromUrlOutput,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.load_markdown_from_url.seq import (
    load_md_from_url,
)

HANDLERS: dict = {**_CU_HANDLERS, **_HTM_HANDLERS}

__all__ = [
    "crawl_url",
    "CrawlUrlInput",
    "CrawlUrlOutput",
    "html_to_markdown",
    "HtmlToMarkdownInput",
    "HtmlToMarkdownOutput",
    "load_md_from_url",
    "LoadMdFromUrlInput",
    "LoadMdFromUrlOutput",
    "HANDLERS",
]
