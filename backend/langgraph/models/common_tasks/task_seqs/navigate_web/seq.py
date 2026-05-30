"""navigate_web — TaskSeq pipeline: propose URL, load Markdown, study and extract web content.

Orchestration
-------------
Step 1 — ``propose_web_knowledge_urls``:
    Maps the equity symbol to the Yahoo Finance options URL.

Step 2 — per-URL pipeline:
    a. ``load_md_from_url`` (TaskSeq): ``crawl_url`` → ``html_to_markdown``,
       with ``llm_orchestration`` fallback on crawl failure.
    b. ``study_web_content``: streaming LLM generation of a stdlib-only Python
       transform script that reads Markdown from stdin and extracts structured
       financial JSON.
    c. ``run_sandbox``: execute the script with ``source_markdown`` piped as
       stdin; ``stdout`` holds the extracted financial JSON for downstream
       ingestion.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from backend.langgraph.models.common_tasks.run_sandbox import (
    RunSandboxInput,
    run_sandbox,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.load_markdown_from_url.seq import (
    load_md_from_url,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.load_markdown_from_url.models import (
    LoadMdFromUrlInput,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.models import (
    NavigateWebInput,
    NavigateWebOutput,
    NavigateWebPerUrlOutput,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.propose_web_knowledge_urls import (
    ProposeWebKnowledgeUrlsInput,
    ProposeWebKnowledgeUrlsOutput,
    propose_web_knowledge_urls,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.study_web_content import (
    StudyWebContentInput,
    study_web_content,
)
from backend.langgraph.models.models import NodeContext
from backend.langgraph.models.task_seq import TaskSeq

logger = logging.getLogger(__name__)

_SEQ_NAME = "navigate_web"


async def _run_single_url(
    run_task_fn: Callable[..., Awaitable[Any]],
    ctx: NodeContext,
    url: str,
    seq_input: NavigateWebInput,
) -> NavigateWebPerUrlOutput | None:
    """Run load_md_from_url → study_web_content → run_sandbox for one URL.

    Args:
        run_task_fn: Bound ``self.run_task`` from the hosting node.
        ctx:         Current node context.
        url:         Target URL to crawl and extract.
        seq_input:   Top-level pipeline input (provides objective, schema, etc.).

    Returns:
        :class:`NavigateWebPerUrlOutput` on success, ``None`` if any step raises.
    """
    try:
        load_md_out = await load_md_from_url.run(
            run_task_fn,
            ctx,
            LoadMdFromUrlInput(
                url=url,
                objective=seq_input.objective,
                max_links=seq_input.max_links,
            ),
        )

        study_result = await run_task_fn(
            study_web_content,
            ctx,
            StudyWebContentInput(
                markdown=load_md_out.html_to_markdown.markdown,
                source_url=load_md_out.crawl_url.url,
                objective=seq_input.objective,
                output_json_schema=seq_input.output_json_schema,
                additional_context=seq_input.additional_context,
            ),
        )
        study_output = study_result.content

        sandbox_result = await run_task_fn(
            run_sandbox,
            ctx,
            RunSandboxInput(
                script=study_output.transform_script,
                language="python",
                stdin=study_output.source_markdown,
            ),
        )

        return NavigateWebPerUrlOutput(
            crawl_url=load_md_out.crawl_url,
            html_to_markdown=load_md_out.html_to_markdown,
            study_web_content=study_output,
            run_sandbox=sandbox_result.content,
        )
    except Exception as exc:
        logger.error("navigate_web: pipeline failed for url=%r: %s", url, exc)
        return None


async def _pipeline(
    run_task_fn: Callable[..., Awaitable[Any]],
    ctx: NodeContext,
    seq_input: NavigateWebInput,
) -> NavigateWebOutput:
    """Run propose_web_knowledge_urls → parallel per-URL (load_md → study → sandbox).

    Step 1 calls ``propose_web_knowledge_urls`` to obtain a list of target URLs
    using the configured strategy.  Step 2 launches one coroutine per URL and
    gathers them concurrently; failed URLs are logged and excluded from results.

    Args:
        run_task_fn: Bound ``self.run_task`` from the hosting node.
        ctx:         Current node context.
        seq_input:   Typed pipeline input.

    Returns:
        :class:`NavigateWebOutput` with proposal output and per-URL results.
    """
    # Step 1: propose one or more URLs for the symbol.
    propose_result = await run_task_fn(
        propose_web_knowledge_urls,
        ctx,
        ProposeWebKnowledgeUrlsInput(
            symbol=seq_input.symbol,
        ),
    )
    propose_output: ProposeWebKnowledgeUrlsOutput = propose_result.content

    # Step 2: run per-URL pipeline in parallel.
    urls = [propose_output.url]
    per_url_coros = [
        _run_single_url(run_task_fn, ctx, url, seq_input)
        for url in urls
    ]
    raw_results: list[NavigateWebPerUrlOutput | None | BaseException] = (
        await asyncio.gather(*per_url_coros, return_exceptions=True)
    )

    results: list[NavigateWebPerUrlOutput] = []
    for url, outcome in zip(urls, raw_results):
        if isinstance(outcome, BaseException):
            logger.error("navigate_web: unhandled exception for url=%r: %s", url, outcome)
        elif outcome is not None:
            results.append(outcome)

    return NavigateWebOutput(
        propose_web_knowledge_urls=propose_output,
        results=results,
    )


navigate_web: TaskSeq[NavigateWebInput, NavigateWebOutput] = TaskSeq(
    name=_SEQ_NAME,
    description=(
        "Two-step pipeline: (1) propose_web_knowledge_urls — map an equity symbol to the "
        "Yahoo Finance options URL; (2) load_md_from_url (crawl + html-to-markdown with LLM "
        "orchestration fallback) then study_web_content + run_sandbox to produce structured "
        "financial JSON from the page content."
    ),
    tasks=[propose_web_knowledge_urls, *load_md_from_url.tasks, study_web_content, run_sandbox],
    input_type=NavigateWebInput,
    output_type=NavigateWebOutput,
    pipeline_fn=_pipeline,
)

__all__ = [
    "navigate_web",
    "NavigateWebInput",
    "NavigateWebOutput",
    "NavigateWebPerUrlOutput",
]

