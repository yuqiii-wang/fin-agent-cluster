"""filter_co_index.py — Step 4: remove peers that share no index with the target."""

from __future__ import annotations

import asyncio
import logging

from backend.db.postgres.queries.fin_markets_indexes import get_symbol_index_codes
from backend.langgraph.nodes.prepare_peers.agent_steps.constants import STEP_FILTER_CO_INDEX
from backend.langgraph.nodes.prepare_peers.agent_steps.state import StepResult, StepRunContext

logger = logging.getLogger(__name__)


async def step_filter_co_index(sctx: StepRunContext) -> None:
    """Step 4: remove peers not sharing any market index with the target.

    When the target has no index codes in the DB, all peers pass through
    (fail-open behaviour — index data may simply not be loaded yet).

    This step has no input overrides and always operates on ``s.valid_peers``.

    On success, updates ``sctx.s.valid_peers`` to only include co-index peers.
    Peers removed by this filter are added to ``sctx.g.excluded_peers``.

    Args:
        sctx: Step run context.

    Raises:
        ValueError: When all valid peers are removed by the co-index filter.
    """
    g, s = sctx.g, sctx.s

    target_index_set = await get_symbol_index_codes(g.target)
    if not target_index_set:
        s.step_results[STEP_FILTER_CO_INDEX] = StepResult(
            step=STEP_FILTER_CO_INDEX,
            success=True,
            output_summary={"skipped": True, "reason": "target has no index codes"},
        )
        return

    index_check = await asyncio.gather(
        *[get_symbol_index_codes(sym) for sym in s.valid_peers],
        return_exceptions=True,
    )

    index_filtered: list[str] = []
    for sym, res in zip(s.valid_peers, index_check):
        if isinstance(res, Exception):
            index_filtered.append(sym)  # fail-open: index lookup error ≠ disqualification
        elif res.isdisjoint(target_index_set):
            g.excluded_peers.append(sym)
            logger.error(
                "[prepare_peers] iter=%d peer=%s removed: no shared index with target",
                s.iteration,
                sym,
            )
        else:
            index_filtered.append(sym)

    s.valid_peers = index_filtered
    if not s.valid_peers:
        s.step_results[STEP_FILTER_CO_INDEX] = StepResult(
            step=STEP_FILTER_CO_INDEX,
            success=False,
            failure_reason="all peers removed by co-index filter",
        )
        raise ValueError(
            f"[prepare_peers] iter={s.iteration}: all peers removed by co-index filter"
        )

    s.step_results[STEP_FILTER_CO_INDEX] = StepResult(
        step=STEP_FILTER_CO_INDEX,
        success=True,
        output_summary={"valid_peers": s.valid_peers},
    )


__all__ = ["step_filter_co_index"]
