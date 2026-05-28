"""navigate_web.py — Step 2: crawl the proposed URL and extract peer ticker symbols."""

from __future__ import annotations

import json
import logging
from uuid import uuid4

from backend.langgraph.models.common_tasks.task_seqs.navigate_web import (
    NavigateWebInput,
    NavigateWebOutput,
    navigate_web,
)
from backend.langgraph.models.models import TaskContext, TaskOutput
from backend.langgraph.nodes.prepare_peers.agent_steps.constants import STEP_NAVIGATE_WEB
from backend.langgraph.nodes.prepare_peers.agent_steps.state import StepResult, StepRunContext

logger = logging.getLogger(__name__)


async def step_navigate_web(sctx: StepRunContext) -> None:
    """Step 2: crawl the proposed URL and extract peer ticker symbols.

    Checks ``sctx.s.input_overrides`` for:

    - ``"peers"``: list of peer tickers to inject directly, skipping the crawl.

    Falls back to ``g.last_proposed_url`` when ``s.proposed_url`` is empty (i.e.
    when this step is entered without ``step_propose_url`` having run first).

    On success, sets ``sctx.s.new_peers`` and updates ``sctx.g.industry``.

    Args:
        sctx: Step run context.

    Raises:
        ValueError: When no usable peer tickers are extracted, or when no URL is
                    available and no ``"peers"`` override is provided.
        Exception:  Any error from the ``navigate_web`` TaskSeq.
    """
    g, s = sctx.g, sctx.s

    injected_peers: list[str] = s.input_overrides.get("peers", [])
    if injected_peers:
        filtered = [
            p.strip().upper()
            for p in injected_peers
            if p.strip().upper() not in g.excluded_peers
            and p.strip().upper() != g.target
        ]
        s.new_peers = filtered
        s.step_results[STEP_NAVIGATE_WEB] = StepResult(
            step=STEP_NAVIGATE_WEB,
            success=True,
            output_summary={"peer_count": len(filtered), "source": "llm_override"},
        )
        return

    url = s.proposed_url or g.last_proposed_url
    if not url:
        exc = ValueError(
            "no URL available for navigate_web — "
            "propose_url step was skipped with no peers override"
        )
        s.step_results[STEP_NAVIGATE_WEB] = StepResult(
            step=STEP_NAVIGATE_WEB,
            success=False,
            failure_reason=str(exc),
        )
        raise exc

    try:
        nav_out: NavigateWebOutput = await navigate_web.run(
            sctx.run_task,
            sctx.ctx,
            NavigateWebInput(
                url=url,
                objective=sctx.peer_discovery_objective.format(stock_name=sctx.stock_name),
                output_json_schema=sctx.peers_output_schema,
                additional_context=[sctx.peers_extraction_skill],
            ),
        )
        sctx.results[f"{navigate_web.name}_iter{s.iteration}"] = TaskOutput(
            ctx=TaskContext(
                **sctx.ctx.model_dump(),
                task_id=str(uuid4()),
                task_name=navigate_web.name,
            ),
            content=nav_out.model_dump(),
        )

        new_peers: list[str] = []
        if nav_out.run_sandbox.exit_code == 0 and nav_out.run_sandbox.stdout:
            try:
                sandbox_json = json.loads(nav_out.run_sandbox.stdout)
                raw_peers = sandbox_json.get("symbols", [])
                new_peers = [
                    p.strip().upper()
                    for p in raw_peers
                    if isinstance(p, str)
                    and p.strip()
                    and p.strip().upper() not in g.excluded_peers
                    and p.strip().upper() != g.target
                ]
                g.industry = sandbox_json.get("industry", g.industry)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.error(
                    "[prepare_peers] iter=%d sandbox stdout invalid JSON url=%r: %s",
                    s.iteration,
                    url,
                    exc,
                )
        else:
            logger.error(
                "[prepare_peers] iter=%d sandbox failed exit_code=%d url=%r stderr=%r",
                s.iteration,
                nav_out.run_sandbox.exit_code,
                url,
                nav_out.run_sandbox.stderr,
            )

        if not new_peers:
            raise ValueError(f"no usable peer tickers from url={url!r}")

        s.new_peers = new_peers
        s.step_results[STEP_NAVIGATE_WEB] = StepResult(
            step=STEP_NAVIGATE_WEB,
            success=True,
            output_summary={"peer_count": len(new_peers), "peers": new_peers[:10]},
        )
    except Exception as exc:
        s.step_results[STEP_NAVIGATE_WEB] = StepResult(
            step=STEP_NAVIGATE_WEB,
            success=False,
            failure_reason=str(exc),
        )
        raise


__all__ = ["step_navigate_web"]
