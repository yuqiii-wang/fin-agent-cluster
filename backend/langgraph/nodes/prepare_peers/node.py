"""AnalyzePeersNode — Agent node that identifies and validates industry peer companies.

Hierarchy
---------
Thread
  └── prepare_peers  (Agent)
        ├── propose_peer_stocks         (@task → Celery Streaming)             [×1–3]
        ├── get_and_calculate_stats     (TaskSeq → get_stats + calculate_stats)  [×N per iteration, one per peer]
        ├── calculate_corr              (@task → Celery Completion)              [×N per iteration, one per peer]
        └── analyze_peer_corr           (@task → pure computation)               [×1 per iteration]

Agent design — validation loop
-------------------------------
The node runs a deterministic corr-validation loop (up to 3 iterations):

  1. ``propose_peer_stocks`` (streaming LLM) → 5–8 ticker symbols. [FIRST]
  2. ``get_and_calculate_stats`` for target (first iteration) and all new peers in parallel.
  3. ``calculate_corr([target, peer])`` for each valid peer in parallel.
  4. ``analyze_peer_corr`` — threshold-filter all corr scores; confirmed peers trigger
     early exit, rejected extend the excluded list for the next round. [LAST]

After the loop the top ``_MAX_CONFIRMED_PEERS`` confirmed peers by abs(r) are
selected.  If no peer met the threshold the best available are returned
(fallback: top ``_MIN_FALLBACK_PEERS``).

Correlation threshold rationale
--------------------------------
For equity pairs Pearson ≥ 0.75 indicates a strong price co-movement
consistent with shared sector/macro exposure.  Values below 0.4 suggest
unrelated price drivers; values above 0.8 often indicate near-identical
exposure.  0.75 is the gate for "genuine peer".

Predecessor
-----------
``query_node`` — must be completed before ``prepare_peers`` starts.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, ClassVar
from uuid import uuid4

from backend.db.postgres.queries.fin_markets_indexes import get_symbol_index_codes
from backend.db.postgres.types import NodeType
from backend.langgraph.agent.memory.ops import append_memory_entry, get_max_seq_num
from backend.langgraph.lifecycle import read_node_output
from backend.langgraph.models.models import NodeContext, TaskContext, TaskOutput
from backend.langgraph.models.node import BaseNode
from backend.langgraph.models.task import NodeTask
from backend.langgraph.models.common_tasks import (
    calculate_corr, CalculateCorrInput, CalculateCorrOutput,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats import (
    get_and_calculate_stats,
    GetAndCalculateStatsInput,
)
from backend.langgraph.nodes.prepare_peers.models import AnalyzePeersInput, AnalyzePeersOutput
from backend.langgraph.nodes.prepare_peers.tasks.analyze_peer_corr import (
    analyze_peer_corr,
    AnalyzePeerCorrInput,
)
from backend.langgraph.nodes.prepare_peers.tasks.propose_peer_stocks import (
    propose_peer_stocks,
    ProposePeerStocksInput,
)
from backend.langgraph.state import GraphState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Loop constants
# ---------------------------------------------------------------------------

_MAX_ITERATIONS: int = 3
# Number of confirmed peers required to exit the loop early.
_MIN_CONFIRMED_TO_EXIT: int = 2
# Pearson abs(r) ≥ this value is treated as a validated peer.
_CORR_THRESHOLD: float = 0.75
# Period used when fetching and computing stats for peer validation.
# '2y' → yfinance fetches ~500 daily bars → stored as '1day' granularity.
# Daily bars give enough history for SMA_20/50/200 and EMA_12/26 to be fully populated.
_VALIDATION_PERIOD: str = "2y"
# quant_stats granularity for _VALIDATION_PERIOD (from calculate_stats period map).
_VALIDATION_GRANULARITY: str = "1day"
# Correlation lookback in bars — 252 ≈ one year of trading days.
_CORR_WINDOW_BARS: int = 252
# Max peers to keep in final output.
_MAX_CONFIRMED_PEERS: int = 5
# Minimum peers to return even when none reach the corr threshold (fallback).
_MIN_FALLBACK_PEERS: int = 3
# Summary key in the results dict that carries loop metadata to build_output.
_SUMMARY_KEY: str = "__peer_validation_summary__"


class AnalyzePeersNode(BaseNode[AnalyzePeersInput, AnalyzePeersOutput]):
    """Agent node: proposes and corr-validates industry peer companies for a target stock."""

    node_name = "prepare_peers"
    node_type = NodeType.AGENT
    display_name = "Analyze Peers"
    category = "Analysis"
    parallel_group: ClassVar[str] = "analyze_parallel"
    config_fields: ClassVar[list[dict]] = [
        {
            "key": "human_in_the_loop",
            "label": "Review peer analysis",
            "type": "boolean",
            "description": "Pause after peer identification and correlation validation; wait for your approval.",
        },
        {
            "key": "depth",
            "label": "Research depth",
            "type": "select",
            "options": [
                {"value": "shallow", "label": "Shallow — fast overview"},
                {"value": "normal", "label": "Normal — balanced"},
                {"value": "deep", "label": "Deep — thorough"},
            ],
            "description": "Controls how many peer candidates are evaluated per iteration.",
        },
        {
            "key": "max_iterations",
            "label": "Max agent iterations",
            "type": "number",
            "min": 1,
            "max": 5,
            "step": 1,
            "description": "Maximum corr-validation loop iterations for peer identification.",
        },
    ]
    view_type = "Stats"
    tasks: ClassVar[list[NodeTask]] = [
        propose_peer_stocks,
        *get_and_calculate_stats.tasks,
        calculate_corr,
        analyze_peer_corr,
    ]
    _prev_node_names: ClassVar[list[str]] = ["query_node"]

    async def build_input(self, state: GraphState) -> AnalyzePeersInput:
        """Read stock_name from query_node's completed node_executions row.

        Args:
            state: Current GraphState.

        Returns:
            Typed ``AnalyzePeersInput`` populated from the PG replica.
        """
        query_node_id = self._find_node_id_by_name(state, "query_node")
        stock_name = ""
        if query_node_id:
            output = await read_node_output(query_node_id)
            stock_name = output.get("stock_name", "")
        return AnalyzePeersInput(stock_name=stock_name)

    async def build_agent(
        self, ctx: NodeContext, node_input: AnalyzePeersInput
    ) -> dict[str, TaskOutput]:
        """Deterministic corr-validation loop: propose → stats → corr → analyze.

        Up to ``_MAX_ITERATIONS`` rounds, in strict task order:
          1. ``propose_peer_stocks`` (streaming LLM) → 5–8 peer ticker symbols. [FIRST]
          2. ``get_and_calculate_stats`` for target (first iteration only) and all
             new peers in parallel.
          3. ``calculate_corr([target, peer])`` for each valid peer in parallel.
          4. ``analyze_peer_corr`` — threshold-filter corr scores; confirmed peers
             trigger early exit, rejected extend the excluded list. [LAST per iteration]

        After the loop the top ``_MAX_CONFIRMED_PEERS`` confirmed peers by abs(r) are
        selected.  Falls back to the best available when no peer met the threshold.

        Args:
            ctx:        Node context carrying thread/node/task identity.
            node_input: Typed input with ``stock_name``.

        Returns:
            Keyed ``TaskOutput`` dict with a ``_SUMMARY_KEY`` entry that carries
            the final peer selection to ``build_output``.
        """
        target = node_input.stock_name.upper()
        results: dict[str, TaskOutput] = {}
        excluded: list[str] = []
        all_peer_corr: dict[str, float] = {}
        all_confirmed: list[str] = []
        industry = ""
        iterations_run = 0
        target_stats_fetched = False
        # sym → pandas split-orient OHLCV dict for StackCandleStick rendering.
        df_split_map: dict[str, dict] = {}
        # sym → raw (signed) correlation values per metric for the DataFrame view.
        all_corr_detail: dict[str, dict] = {}

        async def _fetch_stats(sym: str) -> str:
            """Fetch and compute stats for *sym*; returns sym on success."""
            seq_out = await get_and_calculate_stats.run(
                self.run_task, ctx,
                GetAndCalculateStatsInput(symbol=sym, period=_VALIDATION_PERIOD),
            )
            if seq_out.calculate_stats.df_split:
                df_split_map[sym] = seq_out.calculate_stats.df_split
            return sym

        async def _calc_corr(sym: str) -> tuple[str, float, TaskOutput]:
            """Compute pairwise corr for *sym* vs *target*; returns (sym, abs_corr, output)."""
            corr_out = await self.run_task(
                calculate_corr, ctx,
                CalculateCorrInput(
                    symbols=[target, sym],
                    granularity=_VALIDATION_GRANULARITY,
                    window_bars=_CORR_WINDOW_BARS,
                ),
            )
            content: CalculateCorrOutput = corr_out.content
            # Prefer SMA/EMA indicator correlation (smoother signal); fall back to
            # raw close-price correlation when indicator data is unavailable.
            indicator_corr = max(
                (
                    abs(mat.get(target, {}).get(sym, 0.0))
                    for mat in content.indicator_matrices.values()
                ),
                default=0.0,
            )
            corr_val = indicator_corr or abs(content.matrix.get(target, {}).get(sym, 0.0))
            # Collect detailed (signed) corr values for the correlation DataFrame.
            sym_detail = {
                "close_corr": content.matrix.get(target, {}).get(sym),
                "sma_20_corr": content.indicator_matrices.get("sma_20", {}).get(target, {}).get(sym),
                "sma_50_corr": content.indicator_matrices.get("sma_50", {}).get(target, {}).get(sym),
                "ema_12_corr": content.indicator_matrices.get("ema_12", {}).get(target, {}).get(sym),
                "ema_26_corr": content.indicator_matrices.get("ema_26", {}).get(target, {}).get(sym),
            }
            # Keep detail from the iteration with the highest abs corr.
            if corr_val > all_peer_corr.get(sym, 0.0) or sym not in all_corr_detail:
                all_corr_detail[sym] = sym_detail
            return sym, corr_val, corr_out

        for iteration in range(1, _MAX_ITERATIONS + 1):
            iterations_run = iteration

            # ── Step 1: propose_peer_stocks (FIRST task) ─────────────────────
            propose_out = await self.run_task(
                propose_peer_stocks, ctx,
                ProposePeerStocksInput(
                    stock_name=node_input.stock_name,
                    excluded_peers=excluded,
                    iteration=iteration,
                ),
            )
            results[f"{propose_peer_stocks.name}_iter{iteration}"] = propose_out
            industry = propose_out.content.industry

            new_peers = [
                p for p in propose_out.content.peers
                if p and p not in excluded and p != target
            ]
            if not new_peers:
                logger.error(
                    "[prepare_peers] iter=%d LLM returned no new peers (excluded=%s)",
                    iteration, excluded,
                )
                break

            # ── Step 2: get stats in parallel (target first iter + all new peers) ──
            syms_to_fetch = ([] if target_stats_fetched else [target]) + new_peers
            stats_gather = await asyncio.gather(
                *[_fetch_stats(sym) for sym in syms_to_fetch],
                return_exceptions=True,
            )

            if not target_stats_fetched:
                target_res = stats_gather[0]
                if isinstance(target_res, Exception):
                    raise ValueError(
                        f"[AP-003] Target stock {target!r} stats fetch/calc failed: {target_res}"
                    ) from target_res
                target_stats_fetched = True
                peer_stats_iter = zip(new_peers, stats_gather[1:])
            else:
                peer_stats_iter = zip(new_peers, stats_gather)

            failed_syms: set[str] = set()
            for sym, res in peer_stats_iter:
                if isinstance(res, Exception):
                    failed_syms.add(sym)
                    excluded.append(sym)
                    logger.error(
                        "[prepare_peers] iter=%d stats failed for %s: %s", iteration, sym, res,
                    )

            valid_peers = [s for s in new_peers if s not in failed_syms]
            if not valid_peers:
                logger.error("[prepare_peers] iter=%d all peers failed stats fetch", iteration)
                continue  # AP-004

            # ── Co-index filter (post-stats): retain only peers that share ≥1 benchmark index ──
            # stock_index_memberships is populated by calculate_stats, so this must run after step 2.
            target_index_set = await get_symbol_index_codes(target)
            if target_index_set:
                index_check = await asyncio.gather(
                    *[get_symbol_index_codes(sym) for sym in valid_peers],
                    return_exceptions=True,
                )
                index_filtered: list[str] = []
                for sym, res in zip(valid_peers, index_check):
                    if isinstance(res, Exception):
                        index_filtered.append(sym)  # fail-open
                    elif res.isdisjoint(target_index_set):
                        excluded.append(sym)
                        logger.error(
                            "[prepare_peers] iter=%d peer=%s removed: no shared index with target",
                            iteration, sym,
                        )
                    else:
                        index_filtered.append(sym)
                valid_peers = index_filtered

            if not valid_peers:
                logger.error(
                    "[prepare_peers] iter=%d all peers removed by co-index filter (excluded=%s)",
                    iteration, excluded,
                )
                continue

            # ── Step 3: calculate_corr per peer in parallel ───────────────────
            corr_gather = await asyncio.gather(
                *[_calc_corr(sym) for sym in valid_peers],
                return_exceptions=True,
            )

            iter_peer_corrs: dict[str, float] = {}
            for sym, res in zip(valid_peers, corr_gather):
                if isinstance(res, Exception):
                    excluded.append(sym)
                    logger.error(
                        "[prepare_peers] iter=%d corr failed for %s: %s", iteration, sym, res,
                    )
                else:
                    sym2, corr_val, corr_out = res
                    iter_peer_corrs[sym2] = corr_val
                    all_peer_corr[sym2] = max(all_peer_corr.get(sym2, 0.0), corr_val)
                    results[f"{calculate_corr.name}_{sym2}_iter{iteration}"] = corr_out

            if not iter_peer_corrs:
                logger.error("[prepare_peers] iter=%d all peers failed corr", iteration)
                continue  # AP-004

            # ── Step 4: analyze_peer_corr (LAST task per iteration) ───────────
            apc_out = await self.run_task(
                analyze_peer_corr, ctx,
                AnalyzePeerCorrInput(
                    target=target,
                    peer_correlations=iter_peer_corrs,
                    corr_threshold=_CORR_THRESHOLD,
                ),
            )
            results[f"{analyze_peer_corr.name}_iter{iteration}"] = apc_out

            excluded.extend(apc_out.content.rejected_peers)
            # Exclude confirmed peers too so subsequent iterations propose fresh symbols.
            excluded.extend(apc_out.content.confirmed_peers)
            all_confirmed.extend(apc_out.content.confirmed_peers)

            # Update base agent node memory with this iteration's corr results.
            # Subsequent propose_peer_stocks calls receive it via TaskInput.memory.
            mem_entries = [
                {
                    "symbol": sym,
                    "corr": round(corr_val, 4),
                    "status": "confirmed" if sym in apc_out.content.confirmed_peers else "rejected",
                }
                for sym, corr_val in iter_peer_corrs.items()
            ]
            self.update_agent_memory(ctx, mem_entries)
            # Persist to DB so the UI Memory tab reflects this iteration's results.
            seq_num = await get_max_seq_num(ctx.node_id) + 1
            await append_memory_entry(
                ctx.thread_id,
                ctx.node_id,
                "task_result",
                {
                    "tool_name": "analyze_peer_corr",
                    "result": {
                        "iteration": iteration,
                        "confirmed_peers": apc_out.content.confirmed_peers,
                        "rejected_peers": apc_out.content.rejected_peers,
                        "corr_scores": {sym: round(v, 4) for sym, v in iter_peer_corrs.items()},
                    },
                },
                seq_num,
            )

            # Exit early once enough peers are confirmed across all iterations.
            _seen: set[str] = set()
            unique_confirmed_so_far = [
                s for s in all_confirmed if not (_seen.__contains__(s) or _seen.add(s))
            ]
            if len(unique_confirmed_so_far) >= _MIN_CONFIRMED_TO_EXIT:
                break  # Enough validated peers found — exit early

        # ── Final selection: top peers by abs corr with target ────────────────
        seen: set[str] = set()
        unique_confirmed = [s for s in all_confirmed if not (s in seen or seen.add(s))]
        confirmed = sorted(
            unique_confirmed, key=lambda s: all_peer_corr.get(s, 0.0), reverse=True
        )
        confirmed = confirmed[:_MAX_CONFIRMED_PEERS]

        if not confirmed:
            # AP-005: no peer reached threshold — return best available
            logger.error(
                "[prepare_peers] no peer reached corr threshold %.2f after %d iterations; "
                "using best available. all_peer_corr=%s",
                _CORR_THRESHOLD, iterations_run, all_peer_corr,
            )
            sorted_all = sorted(all_peer_corr.items(), key=lambda x: x[1], reverse=True)
            confirmed = [sym for sym, _ in sorted_all[:_MIN_FALLBACK_PEERS]]

        # Build df_splits for StackCandleStick: target first, then confirmed peers.
        all_syms_ordered = [target] + [p for p in confirmed if p != target]
        peer_df_splits = [
            {"symbol": sym, "label": sym, "df_split": df_split_map[sym]}
            for sym in all_syms_ordered
            if sym in df_split_map and df_split_map[sym]
        ]

        # Build correlation DataFrame (pandas split-orient) for the DataFrame stats view.
        _CORR_COLS = ["close_corr", "sma_20_corr", "sma_50_corr", "ema_12_corr", "ema_26_corr"]
        corr_rows: list[list] = []
        corr_index: list[str] = []
        for sym in confirmed:
            detail = all_corr_detail.get(sym, {})
            corr_rows.append([detail.get(col) for col in _CORR_COLS])
            corr_index.append(sym)
        # Only include columns that have at least one non-None value.
        avail_cols = [
            col for col in _CORR_COLS
            if corr_rows and any(row[_CORR_COLS.index(col)] is not None for row in corr_rows)
        ]
        col_indices = [_CORR_COLS.index(c) for c in avail_cols]
        corr_df_split: dict = (
            {
                "index": corr_index,
                "columns": avail_cols,
                "data": [[row[i] for i in col_indices] for row in corr_rows],
            }
            if corr_index else {}
        )

        # Store summary for build_output via a synthetic TaskOutput.
        summary_task_ctx = TaskContext(
            **ctx.model_dump(),
            task_id=str(uuid4()),
            task_name=_SUMMARY_KEY,
        )
        results[_SUMMARY_KEY] = TaskOutput(
            ctx=summary_task_ctx,
            content={
                "industry": industry,
                "confirmed_peers": confirmed,
                "peer_correlations": all_peer_corr,
                "iterations_run": iterations_run,
                "df_splits": peer_df_splits,
                "corr_df_split": corr_df_split,
            },
        )
        return results

    def build_output(self, results: dict[str, TaskOutput]) -> AnalyzePeersOutput:
        """Compose node output from the loop summary stored under ``_SUMMARY_KEY``.

        Args:
            results: Keyed task outputs from ``build_agent``.

        Returns:
            ``AnalyzePeersOutput`` with validated peers, corr scores, and iteration count.
        """
        summary = results.get(_SUMMARY_KEY)
        if summary is None:
            raise RuntimeError(
                "AP-003: peer validation summary missing from agent results — "
                "build_agent did not complete successfully."
            )
        data: dict = summary.content
        return AnalyzePeersOutput(
            df_splits=data.get("df_splits", []),
            corr_df_split=data.get("corr_df_split", {}),
        )

    def get_state_updates(self, output: AnalyzePeersOutput) -> dict[str, Any]:
        """No GraphState updates — output stored in node_executions via lifecycle.

        Args:
            output: Completed node output.

        Returns:
            Empty dict.
        """
        return {}


# Module-level callable registered with LangGraph StateGraph.
prepare_peers_node = AnalyzePeersNode()
