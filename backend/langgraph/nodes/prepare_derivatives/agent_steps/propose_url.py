"""propose_url.py — Step 1: build the Yahoo Finance options URL for the target symbol."""

from __future__ import annotations

import logging

from backend.langgraph.models.common_tasks.task_seqs.navigate_web.propose_web_knowledge_urls import (
    ProposeWebKnowledgeUrlsInput,
    propose_web_knowledge_urls,
)
from backend.langgraph.nodes.prepare_derivatives.agent_steps.constants import STEP_PROPOSE_URL
from backend.langgraph.nodes.prepare_derivatives.models.state import DerivativesStepContext

logger = logging.getLogger(__name__)


async def step_propose_url(sctx: DerivativesStepContext) -> None:
    """Step 1: map the target symbol to a Yahoo Finance options URL.

    On success, sets ``sctx.g.web_knowledge_url``.

    Args:
        sctx: Step context.

    Raises:
        ValueError: When ``g.symbol`` is empty (no symbol to fetch URL for).
        Exception:  Any error from the ``propose_web_knowledge_urls`` task.
    """
    g = sctx.g

    if not g.symbol:
        raise ValueError("[PD-001] No stock symbol available — skipping derivatives step loop.")

    try:
        url_out = await sctx.run_task(
            propose_web_knowledge_urls,
            sctx.ctx,
            ProposeWebKnowledgeUrlsInput(symbol=g.symbol),
        )
        sctx.results[propose_web_knowledge_urls.name] = url_out
        g.web_knowledge_url = url_out.content.url
    except Exception as exc:
        logger.error("[PD-002] propose_web_knowledge_urls failed symbol=%r: %s", g.symbol, exc)
        raise


__all__ = ["step_propose_url"]
