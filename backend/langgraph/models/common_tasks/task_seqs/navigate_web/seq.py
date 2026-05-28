"""navigate_web — TaskSeq pipeline: crawl a URL, convert to Markdown, generate transform script, execute in sandbox.

Orchestration
-------------
1. ``crawl_url``          — fetch the page via httpx, extract links from the HTML body.
   If ``crawl_url.is_required_llm_orchestration`` is True and the fetch fails, the
   pipeline invokes ``llm_orchestration`` to decide a recovery action:
   * ``action="retry_propose"`` → re-run ``propose_web_knowledge_urls`` with a new
     symbol, then retry ``crawl_url`` with the resulting URL.
   * ``action="fail"``          → propagate the original exception.
2. ``html_to_markdown``   — convert the raw HTML to clean Markdown via markitdown.
3. ``study_web_content``  — streaming LLM generation of a stdlib-only Python transform
   script that reads Markdown from stdin and extracts structured financial JSON.
   Outputs ``source_markdown`` (original Markdown) and ``transform_script``.
4. ``run_sandbox``         — execute the transform script with ``source_markdown`` piped
   as stdin; ``stdout`` holds the extracted financial JSON for downstream ingestion.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from backend.langgraph.models.common_tasks.run_sandbox import (
    RunSandboxInput,
    run_sandbox,
)
from backend.langgraph.models.common_tasks.llm_orchestration import (
    LlmOrchestrationInput,
    llm_orchestration,
)
from backend.langgraph.models.common_tasks.propose_web_knowledge_urls import (
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
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.models import (
    NavigateWebInput,
    NavigateWebOutput,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.study_web_content import (
    StudyWebContentInput,
    study_web_content,
)
from backend.langgraph.models.models import NodeContext
from backend.langgraph.models.task_seq import TaskSeq

logger = logging.getLogger(__name__)

_SEQ_NAME = "navigate_web"


async def _pipeline(
    run_task_fn: Callable[..., Awaitable[Any]],
    ctx: NodeContext,
    seq_input: NavigateWebInput,
) -> NavigateWebOutput:
    """Run crawl_url → html_to_markdown → study_web_content sequentially.

    When ``crawl_url.is_required_llm_orchestration`` is True and the fetch fails,
    ``llm_orchestration`` is invoked to decide whether to retry via a new symbol
    or propagate the failure.

    Args:
        run_task_fn: Bound ``self.run_task`` from the hosting node.
        ctx:         Current node context.
        seq_input:   Typed pipeline input.

    Returns:
        Combined output from all three tasks.
    """
    # 1. Crawl the URL — with LLM orchestration fallback on failure when flagged.
    crawl_output: CrawlUrlOutput = await _crawl_with_orchestration(
        run_task_fn, ctx, seq_input
    )

    # 2. Convert the fetched HTML to Markdown — hard failure propagates.
    md_result = await run_task_fn(
        html_to_markdown,
        ctx,
        HtmlToMarkdownInput(
            raw_html=crawl_output.raw_html,
            source_url=crawl_output.url,
        ),
    )
    md_output = md_result.content

    # 3. LLM streaming transform-script generation — hard failure propagates.
    study_result = await run_task_fn(
        study_web_content,
        ctx,
        StudyWebContentInput(
            markdown=md_output.markdown,
            source_url=crawl_output.url,
            objective=seq_input.objective,
            output_json_schema=seq_input.output_json_schema,
            additional_context=seq_input.additional_context,
        ),
    )
    study_output = study_result.content

    # 4. Execute the transform script in the sandbox with source_markdown as stdin.
    sandbox_result = await run_task_fn(
        run_sandbox,
        ctx,
        RunSandboxInput(
            script=study_output.transform_script,
            language="python",
            stdin=study_output.source_markdown,
        ),
    )

    return NavigateWebOutput(
        crawl_url=crawl_output,
        html_to_markdown=md_output,
        study_web_content=study_output,
        run_sandbox=sandbox_result.content,
    )


async def _crawl_with_orchestration(
    run_task_fn: Callable[..., Awaitable[Any]],
    ctx: NodeContext,
    seq_input: NavigateWebInput,
) -> CrawlUrlOutput:
    """Attempt crawl_url; on failure invoke llm_orchestration if flagged.

    On ``crawl_url.is_required_llm_orchestration=True`` and a fetch failure:
      1. Runs ``llm_orchestration`` to get a recovery decision.
      2. If ``action="retry_propose"``: re-runs ``propose_web_knowledge_urls``
         with the LLM-suggested symbol and retries ``crawl_url``.
      3. If ``action="fail"`` or orchestration itself fails: re-raises the
         original crawl exception.

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

        # Ask the LLM how to recover.
        try:
            orch_result = await run_task_fn(
                llm_orchestration,
                ctx,
                LlmOrchestrationInput(
                    failed_task_name=crawl_url.name,
                    error_message=str(crawl_exc),
                    original_url=seq_input.url,
                    objective=seq_input.objective,
                ),
            )
        except Exception as orch_exc:
            logger.error(
                "llm_orchestration itself failed after crawl_url failure url=%r: %s",
                seq_input.url, orch_exc,
            )
            raise crawl_exc from None

        orch_output = orch_result.content
        if orch_output.action != "retry_propose" or not orch_output.new_symbol:
            logger.error(
                "llm_orchestration decided action=%r for url=%r — propagating crawl failure",
                orch_output.action, seq_input.url,
            )
            raise crawl_exc from None

        # Re-propose a URL with the new symbol and retry the crawl.
        try:
            propose_result = await run_task_fn(
                propose_web_knowledge_urls,
                ctx,
                ProposeWebKnowledgeUrlsInput(symbol=orch_output.new_symbol),
            )
            retry_url = propose_result.content.url
        except Exception as propose_exc:
            logger.error(
                "propose_web_knowledge_urls failed for llm-proposed symbol=%r: %s",
                orch_output.new_symbol, propose_exc,
            )
            raise crawl_exc from None

        retry_result = await run_task_fn(
            crawl_url,
            ctx,
            CrawlUrlInput(url=retry_url, max_links=seq_input.max_links),
        )
        return retry_result.content


navigate_web: TaskSeq[NavigateWebInput, NavigateWebOutput] = TaskSeq(
    name=_SEQ_NAME,
    description=(
        "Sequential pipeline: fetch a web page (crawl_url), convert its HTML body to "
        "Markdown (html_to_markdown), generate a Python extraction script via an LLM "
        "(study_web_content), then execute the script in an isolated sandbox (run_sandbox) "
        "to produce a structured financial JSON from the page content."
    ),
    tasks=[crawl_url, html_to_markdown, study_web_content, run_sandbox, llm_orchestration],
    input_type=NavigateWebInput,
    output_type=NavigateWebOutput,
    pipeline_fn=_pipeline,
)

__all__ = [
    "navigate_web",
    "NavigateWebInput",
    "NavigateWebOutput",
]
