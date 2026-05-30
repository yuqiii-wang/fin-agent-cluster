"""navigate_web — TaskSeq pipeline: propose URLs, load Markdown, study and extract.

Orchestration
-------------
Step 1 — ``propose_web_knowledge_urls``:
    Maps the equity symbol to one or more URLs via ``fixed_rule`` or ``web_search``.

Step 2 — parallel per-URL pipeline:
    For each URL: ``load_md_from_url`` (crawl + html-to-markdown with LLM orchestration
    fallback) → ``study_web_content`` → ``run_sandbox``.
"""

from backend.langgraph.models.common_tasks.task_seqs.navigate_web.load_markdown_from_url import (
    CrawlUrlInput,
    CrawlUrlOutput,
    crawl_url,
    HtmlToMarkdownInput,
    HtmlToMarkdownOutput,
    html_to_markdown,
    load_md_from_url,
    LoadMdFromUrlInput,
    LoadMdFromUrlOutput,
    HANDLERS as _LMD_HANDLERS,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.study_web_content import (
    StudyWebContentInput,
    StudyWebContentOutput,
    study_web_content,
    HANDLERS as _SWC_HANDLERS,
    STREAM_PROMPT_BUILDERS as _SWC_SPB,
)
from backend.langgraph.models.common_tasks.llm_orchestration_on_failure import (
    LlmOrchestrationInput,
    LlmOrchestrationOutput,
    StepResult,
    StepInfo,
    llm_orchestration_on_failure,
    HANDLERS as _LO_HANDLERS,
    STREAM_PROMPT_BUILDERS as _LO_SPB,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.propose_web_knowledge_urls import (
    ProposeWebKnowledgeUrlsInput,
    ProposeWebKnowledgeUrlsOutput,
    propose_web_knowledge_urls,
    HANDLERS as _PWKU_HANDLERS,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.models import (
    NavigateWebInput,
    NavigateWebOutput,
    NavigateWebPerUrlOutput,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.seq import (
    navigate_web,
)

HANDLERS: dict = {**_LMD_HANDLERS, **_SWC_HANDLERS, **_LO_HANDLERS, **_PWKU_HANDLERS}
STREAM_PROMPT_BUILDERS: dict = {**_SWC_SPB, **_LO_SPB}

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
    "study_web_content",
    "StudyWebContentInput",
    "StudyWebContentOutput",
    "llm_orchestration_on_failure",
    "LlmOrchestrationInput",
    "LlmOrchestrationOutput",
    "StepResult",
    "StepInfo",
    "propose_web_knowledge_urls",
    "ProposeWebKnowledgeUrlsInput",
    "ProposeWebKnowledgeUrlsOutput",
    "navigate_web",
    "NavigateWebInput",
    "NavigateWebOutput",
    "NavigateWebPerUrlOutput",
    "HANDLERS",
    "STREAM_PROMPT_BUILDERS",
]
