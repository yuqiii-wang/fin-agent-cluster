"""load_markdown.py — Step 1: propose URLs then crawl + convert to Markdown."""

from __future__ import annotations

import asyncio
import logging

from backend.langgraph.models.common_tasks.task_seqs.navigate_web.load_markdown_from_url.seq import (
    load_md_from_url,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.load_markdown_from_url.models import (
    LoadMdFromUrlInput,
    LoadMdFromUrlOutput,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.propose_web_knowledge_urls import (
    ProposeWebKnowledgeUrlsInput,
    propose_web_knowledge_urls,
)
from backend.langgraph.nodes.prepare_derivatives.agent_steps.extraction_schema import (
    NAVIGATE_OBJECTIVE,
)
from backend.langgraph.nodes.prepare_derivatives.models.state import DerivativesStepContext

logger = logging.getLogger(__name__)


async def step_load_markdown(sctx: DerivativesStepContext) -> None:
    """Step 1: propose financial data URL(s) then crawl and convert to Markdown.

    Calls ``propose_web_knowledge_urls`` to map the equity symbol to its data
    URL, then runs ``load_md_from_url`` (crawl + html-to-markdown) for each URL
    in parallel.  Successful Markdown pages are stored in ``g.md_pages`` for the
    downstream ``step_study_web`` step, and the first page in ``g.load_md_output``
    as a fallback for ``step_get_stats``.

    Raises on failure (no symbol, no usable Markdown page) so the agent loop can
    trigger orchestration-driven recovery.

    Args:
        sctx: Step context.

    Raises:
        RuntimeError: When no symbol is available or no Markdown page loads.
    """
    g = sctx.g

    if not g.symbol:
        raise RuntimeError("[PD-001] No stock symbol available for load_markdown step.")

    objective = NAVIGATE_OBJECTIVE.format(symbol=g.symbol)

    propose_result = await sctx.run_task(
        propose_web_knowledge_urls,
        sctx.ctx,
        ProposeWebKnowledgeUrlsInput(symbol=g.symbol),
    )
    propose_output = propose_result.content
    urls = [propose_output.url]

    async def _load(url: str) -> LoadMdFromUrlOutput | None:
        try:
            return await load_md_from_url.run(
                sctx.run_task,
                sctx.ctx,
                LoadMdFromUrlInput(url=url, objective=objective),
            )
        except Exception as exc:
            logger.error("[PD-002] load_md_from_url failed for url=%r: %s", url, exc)
            return None

    raw = await asyncio.gather(*(_load(u) for u in urls), return_exceptions=True)

    pages: list[LoadMdFromUrlOutput] = []
    for url, outcome in zip(urls, raw):
        if isinstance(outcome, BaseException):
            logger.error("[PD-002] unhandled exception loading url=%r: %s", url, outcome)
        elif outcome is not None:
            pages.append(outcome)

    if not pages:
        raise RuntimeError(
            f"[PD-003] no Markdown page loaded for symbol={g.symbol!r} url={propose_output.url!r}"
        )

    g.md_pages = pages
    g.load_md_output = pages[0]


__all__ = ["step_load_markdown"]
