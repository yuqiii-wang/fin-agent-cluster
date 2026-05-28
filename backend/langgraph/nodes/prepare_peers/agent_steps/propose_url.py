"""propose_url.py — Step 1: propose a peer-discovery URL via the LLM."""

from __future__ import annotations

import logging

from backend.langgraph.nodes.prepare_peers.agent_steps.constants import STEP_PROPOSE_URL
from backend.langgraph.nodes.prepare_peers.agent_steps.state import StepResult, StepRunContext
from backend.langgraph.nodes.prepare_peers.tasks.propose_peer_urls import (
    ProposePeerUrlsInput,
    propose_peer_urls,
)

logger = logging.getLogger(__name__)


async def step_propose_url(sctx: StepRunContext) -> None:
    """Step 1: propose a research URL for peer discovery.

    Checks ``sctx.s.input_overrides`` for:

    - ``"custom_url"``:      Use this URL directly and skip the LLM proposal.
    - ``"stock_name_hint"``: Override the stock name hint passed to the LLM.

    On success, sets ``sctx.s.proposed_url`` and appends the URL to
    ``sctx.g.excluded_urls`` and ``sctx.g.last_proposed_url``.

    Args:
        sctx: Step run context.

    Raises:
        ValueError: When ``propose_peer_urls`` returns an empty URL.
        Exception:  Any other error from the ``propose_peer_urls`` task.
    """
    g, s = sctx.g, sctx.s

    custom_url: str = s.input_overrides.get("custom_url", "")
    if custom_url:
        g.excluded_urls.append(custom_url)
        g.last_proposed_url = custom_url
        s.proposed_url = custom_url
        s.step_results[STEP_PROPOSE_URL] = StepResult(
            step=STEP_PROPOSE_URL,
            success=True,
            output_summary={"url": custom_url, "source": "llm_override"},
        )
        return

    stock_name_hint: str = s.input_overrides.get("stock_name_hint", sctx.stock_name)
    try:
        propose_out = await sctx.run_task(
            propose_peer_urls,
            sctx.ctx,
            ProposePeerUrlsInput(
                stock_name=stock_name_hint,
                excluded_urls=g.excluded_urls,
                iteration=s.iteration,
            ),
        )
        sctx.results[f"{propose_peer_urls.name}_iter{s.iteration}"] = propose_out
        peer_url: str = propose_out.content.url
        if not peer_url:
            raise ValueError("propose_peer_urls returned empty URL")
        g.excluded_urls.append(peer_url)
        g.last_proposed_url = peer_url
        s.proposed_url = peer_url
        s.step_results[STEP_PROPOSE_URL] = StepResult(
            step=STEP_PROPOSE_URL,
            success=True,
            output_summary={"url": peer_url},
        )
    except Exception as exc:
        s.step_results[STEP_PROPOSE_URL] = StepResult(
            step=STEP_PROPOSE_URL,
            success=False,
            failure_reason=str(exc),
        )
        raise


__all__ = ["step_propose_url"]
