"""load_md_from_url — TaskSeq: fetch a URL and convert its HTML to Markdown.

Orchestration
-------------
1. ``crawl_url``        — httpx async fetch + link extraction.
2. ``html_to_markdown`` — markitdown HTML → Markdown conversion.

On ``crawl_url`` failure and ``crawl_url.is_required_llm_orchestration=True``,
``llm_orchestration_on_failure`` is invoked to decide recovery:
  * ``action="retry_from_step"`` with ``retry_from_step="propose_url"`` and
    ``input_overrides={"stock_name_hint": "<ticker>"}`` → re-run
    ``propose_web_knowledge_urls`` with the hint, then retry ``crawl_url``.
  * any other action → propagate the original exception.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from backend.langgraph.models.common_tasks.llm_orchestration_on_failure import (
    LlmOrchestrationInput,
    StepInfo,
    StepResult,
    llm_orchestration_on_failure,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.propose_web_knowledge_urls import (
    ProposeWebKnowledgeUrlsInput,
    propose_web_knowledge_urls,
)
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

_STEP_PROPOSE_URL = "propose_url"
_STEP_CRAWL_URL = "crawl_url"
_STEP_ORDER = [_STEP_PROPOSE_URL, _STEP_CRAWL_URL]

_STEP_INFO = [
    StepInfo(
        name=_STEP_PROPOSE_URL,
        description="Propose a web URL for the target equity symbol.",
        input_override_schema={
            "stock_name_hint": (
                "Alternative equity ticker or company name hint to generate a new URL. "
                "Use when the original URL was blocked or wrong for the symbol."
            ),
        },
    ),
    StepInfo(
        name=_STEP_CRAWL_URL,
        description="Fetch the web page at the proposed URL.",
        input_override_schema={},
    ),
]


async def _pipeline(
    run_task_fn: Callable[..., Awaitable[Any]],
    ctx: NodeContext,
    seq_input: LoadMdFromUrlInput,
) -> LoadMdFromUrlOutput:
    """Run crawl_url → html_to_markdown with LLM orchestration fallback on crawl failure.

    Args:
        run_task_fn: Bound ``self.run_task`` from the hosting node.
        ctx:         Current node context.
        seq_input:   Typed pipeline input.

    Returns:
        Combined output from crawl_url and html_to_markdown.
    """
    crawl_out: CrawlUrlOutput = await _crawl_with_orchestration(
        run_task_fn, ctx, seq_input
    )

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


async def _crawl_with_orchestration(
    run_task_fn: Callable[..., Awaitable[Any]],
    ctx: NodeContext,
    seq_input: LoadMdFromUrlInput,
) -> CrawlUrlOutput:
    """Attempt crawl_url; on failure invoke llm_orchestration_on_failure if flagged.

    On ``crawl_url.is_required_llm_orchestration=True`` and a fetch failure:
      1. Runs ``llm_orchestration_on_failure`` with step registry context to get a recovery decision.
      2. If ``action="retry_from_step"`` and ``retry_from_step="propose_url"`` with a
         ``stock_name_hint`` override: re-runs ``propose_web_knowledge_urls`` with the
         hint and retries ``crawl_url`` with the new URL.
      3. Otherwise: re-raises the original crawl exception.

    Args:
        run_task_fn: Bound ``self.run_task`` from the hosting node.
        ctx:         Current node context.
        seq_input:   Typed pipeline input.

    Returns:
        :class:`CrawlUrlOutput` from the successful (possibly retried) crawl.

    Raises:
        Exception: Original crawl exception when no recovery is possible.
    """
    try:
        result = await run_task_fn(
            crawl_url,
            ctx,
            CrawlUrlInput(url=seq_input.url, max_links=seq_input.max_links),
        )
        return result.content
    except Exception as crawl_exc:
        if not crawl_url.is_required_llm_orchestration:
            raise

        try:
            orch_result = await run_task_fn(
                llm_orchestration_on_failure,
                ctx,
                LlmOrchestrationInput(
                    iteration=1,
                    max_iterations=1,
                    target=seq_input.url,
                    objective=seq_input.objective,
                    step_order=_STEP_ORDER,
                    step_info=_STEP_INFO,
                    step_results=[
                        StepResult(
                            step=_STEP_CRAWL_URL,
                            success=False,
                            output_summary={"url": seq_input.url},
                            failure_reason=str(crawl_exc),
                        )
                    ],
                    failed_step=_STEP_CRAWL_URL,
                    failure_reason=str(crawl_exc),
                    context_summary={"original_url": seq_input.url},
                    finish_condition="crawl succeeds and Markdown is available",
                ),
            )
        except Exception as orch_exc:
            logger.error(
                "llm_orchestration_on_failure itself failed after crawl_url failure url=%r: %s",
                seq_input.url,
                orch_exc,
            )
            raise crawl_exc from None

        orch_output = orch_result.content
        stock_name_hint = (orch_output.input_overrides or {}).get("stock_name_hint", "")
        if (
            orch_output.action != "retry_from_step"
            or orch_output.retry_from_step != _STEP_PROPOSE_URL
            or not stock_name_hint
        ):
            logger.error(
                "llm_orchestration_on_failure decided action=%r retry_from_step=%r for url=%r"
                " — propagating crawl failure",
                orch_output.action,
                orch_output.retry_from_step,
                seq_input.url,
            )
            raise crawl_exc from None

        try:
            propose_result = await run_task_fn(
                propose_web_knowledge_urls,
                ctx,
                ProposeWebKnowledgeUrlsInput(symbol=stock_name_hint),
            )
            retry_url = propose_result.content.urls[0]
        except Exception as propose_exc:
            logger.error(
                "propose_web_knowledge_urls failed for llm-proposed hint=%r: %s",
                stock_name_hint,
                propose_exc,
            )
            raise crawl_exc from None

        retry_result = await run_task_fn(
            crawl_url,
            ctx,
            CrawlUrlInput(url=retry_url, max_links=seq_input.max_links),
        )
        return retry_result.content


load_md_from_url: TaskSeq[LoadMdFromUrlInput, LoadMdFromUrlOutput] = TaskSeq(
    name=_SEQ_NAME,
    description=(
        "Sequential pipeline: fetch a web page (crawl_url) and convert its HTML body to "
        "Markdown (html_to_markdown). On crawl failure, invokes llm_orchestration_on_failure to "
        "decide recovery (retry with a new symbol or propagate the failure)."
    ),
    tasks=[crawl_url, html_to_markdown, llm_orchestration_on_failure],
    input_type=LoadMdFromUrlInput,
    output_type=LoadMdFromUrlOutput,
    pipeline_fn=_pipeline,
)

__all__ = [
    "load_md_from_url",
    "LoadMdFromUrlInput",
    "LoadMdFromUrlOutput",
]
