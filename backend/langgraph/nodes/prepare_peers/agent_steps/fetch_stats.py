"""fetch_stats.py — Step 3: fetch and compute OHLCV stats for the target and new peers."""

from __future__ import annotations

import asyncio
import logging

from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats import (
    GetAndCalculateStatsInput,
    get_and_calculate_stats,
)
from backend.langgraph.nodes.prepare_peers.agent_steps.constants import (
    STEP_FETCH_STATS,
    _VALIDATION_PERIOD,
)
from backend.langgraph.nodes.prepare_peers.agent_steps.state import StepResult, StepRunContext

logger = logging.getLogger(__name__)


async def step_fetch_stats(sctx: StepRunContext) -> None:
    """Step 3: fetch and compute OHLCV stats for the target (first iteration) and new peers.

    Checks ``sctx.s.input_overrides`` for:

    - ``"symbols"``: retry stats fetch for this specific symbol list instead of
      ``s.new_peers`` (useful when only a subset of peers needs re-fetching).

    The target is always fetched on the first iteration (``g.target_stats_fetched``
    guard). Peers that fail stats fetch are added to ``g.excluded_peers``.

    On success, sets ``sctx.s.valid_peers`` and populates ``sctx.g.df_split_map``
    for every successfully fetched symbol.

    Args:
        sctx: Step run context.

    Raises:
        ValueError: When the target stats fetch fails (fatal), or when all peers
                    fail stats fetch.
    """
    g, s = sctx.g, sctx.s

    override_symbols: list[str] = s.input_overrides.get("symbols", [])
    base_peers = override_symbols if override_symbols else s.new_peers

    if not base_peers and g.target_stats_fetched:
        s.step_results[STEP_FETCH_STATS] = StepResult(
            step=STEP_FETCH_STATS,
            success=False,
            failure_reason="no peers to fetch stats for",
        )
        raise ValueError(
            f"[prepare_peers] iter={s.iteration}: no peers provided to fetch_stats"
        )

    syms_to_fetch = ([] if g.target_stats_fetched else [g.target]) + base_peers

    async def _fetch(sym: str) -> str:
        """Fetch and compute stats for *sym*; returns sym on success."""
        seq_out = await get_and_calculate_stats.run(
            sctx.run_task,
            sctx.ctx,
            GetAndCalculateStatsInput(symbol=sym, period=_VALIDATION_PERIOD),
        )
        if seq_out.calculate_stats.df_split:
            g.df_split_map[sym] = seq_out.calculate_stats.df_split
        return sym

    stats_gather = await asyncio.gather(
        *[_fetch(sym) for sym in syms_to_fetch],
        return_exceptions=True,
    )

    if not g.target_stats_fetched:
        target_res = stats_gather[0]
        if isinstance(target_res, Exception):
            s.step_results[STEP_FETCH_STATS] = StepResult(
                step=STEP_FETCH_STATS,
                success=False,
                failure_reason=f"target {g.target!r} stats failed: {target_res}",
            )
            raise ValueError(
                f"[AP-003] Target stock {g.target!r} stats fetch/calc failed: {target_res}"
            ) from target_res
        g.target_stats_fetched = True
        peer_stats_iter = zip(base_peers, stats_gather[1:])
    else:
        peer_stats_iter = zip(base_peers, stats_gather)

    failed_syms: set[str] = set()
    for sym, res in peer_stats_iter:
        if isinstance(res, Exception):
            failed_syms.add(sym)
            g.excluded_peers.append(sym)
            logger.error(
                "[prepare_peers] iter=%d stats failed for %s: %s", s.iteration, sym, res,
            )

    s.valid_peers = [sym for sym in base_peers if sym not in failed_syms]
    if not s.valid_peers:
        s.step_results[STEP_FETCH_STATS] = StepResult(
            step=STEP_FETCH_STATS,
            success=False,
            failure_reason="all peers failed stats fetch",
        )
        raise ValueError(f"[AP-004] iter={s.iteration}: all peers failed stats fetch")

    s.step_results[STEP_FETCH_STATS] = StepResult(
        step=STEP_FETCH_STATS,
        success=True,
        output_summary={
            "valid_peers": s.valid_peers,
            "failed_count": len(failed_syms),
        },
    )


__all__ = ["step_fetch_stats"]
