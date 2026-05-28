"""navigate_web — TaskSeq pipeline: fetch URL, convert HTML to Markdown, LLM-assess.

Orchestration
-------------
1. ``crawl_url``         — httpx async fetch + link extraction.
2. ``html_to_markdown``  — markitdown HTML → Markdown conversion.
3. ``study_web_content`` — streaming LLM assessment (sufficient → results, insufficient → next steps).

On ``crawl_url`` failure, ``llm_orchestration`` is invoked to decide recovery:
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
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.study_web_content import (
    StudyWebContentInput,
    StudyWebContentOutput,
    study_web_content,
    HANDLERS as _SWC_HANDLERS,
    STREAM_PROMPT_BUILDERS as _SWC_SPB,
)
from backend.langgraph.models.common_tasks.llm_orchestration import (
    LlmOrchestrationInput,
    LlmOrchestrationOutput,
    llm_orchestration,
    HANDLERS as _LO_HANDLERS,
    STREAM_PROMPT_BUILDERS as _LO_SPB,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.models import (
    NavigateWebInput,
    NavigateWebOutput,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.seq import (
    navigate_web,
)

HANDLERS: dict = {**_CU_HANDLERS, **_HTM_HANDLERS, **_SWC_HANDLERS, **_LO_HANDLERS}
STREAM_PROMPT_BUILDERS: dict = {**_SWC_SPB, **_LO_SPB}

__all__ = [
    "crawl_url",
    "CrawlUrlInput",
    "CrawlUrlOutput",
    "html_to_markdown",
    "HtmlToMarkdownInput",
    "HtmlToMarkdownOutput",
    "study_web_content",
    "StudyWebContentInput",
    "StudyWebContentOutput",
    "llm_orchestration",
    "LlmOrchestrationInput",
    "LlmOrchestrationOutput",
    "navigate_web",
    "NavigateWebInput",
    "NavigateWebOutput",
    "HANDLERS",
    "STREAM_PROMPT_BUILDERS",
]
