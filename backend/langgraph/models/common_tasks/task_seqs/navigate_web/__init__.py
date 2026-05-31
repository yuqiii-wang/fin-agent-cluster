"""navigate_web — web navigation tasks: propose URLs, load Markdown, study and extract.

Building blocks
---------------
- ``propose_web_knowledge_urls`` — map an equity symbol to one or more URLs.
- ``load_md_from_url`` (TaskSeq)  — ``crawl_url`` → ``html_to_markdown``.
- ``study_web_content``           — streaming LLM: generate a transform script and
                                    detect page barriers (``has_popup``).
- ``propose_playwright_script``   — streaming LLM: generate a barrier-clearing script.

Hosting AGENT nodes compose these into steps and own failure recovery via
``llm_orchestration_on_failure``.
"""

from backend.langgraph.models.common_tasks.task_seqs.navigate_web.propose_playwright_script import (
    ProposePlaywrightScriptInput,
    ProposePlaywrightScriptOutput,
    propose_playwright_script,
    HANDLERS as _PPS_HANDLERS,
    STREAM_PROMPT_BUILDERS as _PPS_SPB,
)
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

HANDLERS: dict = {
    **_LMD_HANDLERS,
    **_SWC_HANDLERS,
    **_LO_HANDLERS,
    **_PWKU_HANDLERS,
    **_PPS_HANDLERS,
}
STREAM_PROMPT_BUILDERS: dict = {**_SWC_SPB, **_LO_SPB, **_PPS_SPB}

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
    "propose_playwright_script",
    "ProposePlaywrightScriptInput",
    "ProposePlaywrightScriptOutput",
    "llm_orchestration_on_failure",
    "LlmOrchestrationInput",
    "LlmOrchestrationOutput",
    "propose_web_knowledge_urls",
    "ProposeWebKnowledgeUrlsInput",
    "ProposeWebKnowledgeUrlsOutput",
    "HANDLERS",
    "STREAM_PROMPT_BUILDERS",
]
