"""AnalyzeIndexNode — Workflow node that fetches and calculates stats for
market-rate index instruments (SOFR 3-Month Futures) and major equity benchmark
indexes (S&P 500, Nasdaq 100, Dow Jones, FTSE 100, Hang Seng, Nikkei 225).

Hierarchy
---------
Thread
  └── prepare_index  (Workflow)
        ├── propose_index               (@task → pure computation)              [×1]
        └── get_and_calculate_stats     (TaskSeq → get_stats + calculate_stats)  [×N instruments, parallel]

Node design
-----------
1. ``propose_index`` (pure computation) → resolves the set of equity benchmark
   indexes to analyse: always includes the six major global indexes plus the
   stock's home index if not already covered.
2. ``get_and_calculate_stats`` runs in parallel for:
   a. Every equity benchmark index returned by ``propose_index`` (ticker-based).
   b. Every macro instrument in the ``'market_index'`` category from
      ``fin_markets.macro_instruments`` (e.g. SOFR 3-Month).

Predecessor
-----------
``query_node`` — must be completed before ``prepare_index`` starts.
Runs in parallel with ``prepare_peers`` and ``analyze_economics``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, ClassVar

from langchain_core.runnables import Runnable, RunnableLambda

from backend.db.postgres.types import NodeType
from backend.db.postgres.queries.fin_markets_macro import load_macro_instruments, MacroInstrument
from backend.langgraph.lifecycle import read_node_output
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats import (
    get_and_calculate_stats,
    GetAndCalculateStatsInput,
)
from backend.langgraph.models.models import NodeContext
from backend.langgraph.models.node import BaseNode
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.prepare_index.models import (
    AnalyzeIndexInput,
    AnalyzeIndexOutput,
    IndexInstrumentResult,
    IndexEquityResult,
)
from backend.langgraph.nodes.prepare_index.tasks.propose_index import (
    propose_index,
    ProposeIndexInput,
    ProposeIndexOutput,
    IndexCandidate,
)
from backend.langgraph.state import GraphState
from backend.quant.stats import STATS_VIEW_TYPE

logger = logging.getLogger(__name__)

_STATS_PERIOD: str = "2y"
_INSTRUMENT_CATEGORY: str = "market_index"


class AnalyzeIndexNode(BaseNode[AnalyzeIndexInput, AnalyzeIndexOutput]):
    """Workflow node: fetches and calculates stats for macro and equity benchmark indexes."""

    node_name = "prepare_index"
    node_type = NodeType.WORKFLOW
    display_name = "Analyze Index"
    category = "Analysis"
    parallel_group: ClassVar[str] = "analyze_parallel"
    config_fields: ClassVar[list[dict]] = [
        {
            "key": "human_in_the_loop",
            "label": "Review index analysis",
            "type": "boolean",
            "description": "Pause after equity benchmark index stats are computed; wait for your approval.",
        },
        {
            "key": "depth",
            "label": "Analysis depth",
            "type": "select",
            "options": [
                {"value": "shallow", "label": "Shallow — fast overview"},
                {"value": "normal", "label": "Normal — balanced"},
                {"value": "deep", "label": "Deep — thorough"},
            ],
            "description": "Controls scope of equity benchmark indexes and historical data analysed.",
        },
    ]
    view_type = "Stats"
    stats_views = [STATS_VIEW_TYPE.STACK_CANDLE_STICK.value]
    tasks: ClassVar[list[NodeTask]] = [propose_index, *get_and_calculate_stats.tasks]
    _prev_node_names: ClassVar[list[str]] = ["query_node"]

    async def build_input(self, state: GraphState) -> AnalyzeIndexInput:
        """Construct node input — reads stock_symbol from query_node output.

        Args:
            state: Current GraphState.

        Returns:
            :class:`AnalyzeIndexInput` with the stats period and stock symbol.
        """
        query_node_id = self._find_node_id_by_name(state, "query_node")
        stock_symbol = ""
        if query_node_id:
            output = await read_node_output(query_node_id)
            stock_symbol = output.get("stock_name", "")
        return AnalyzeIndexInput(period=_STATS_PERIOD, stock_symbol=stock_symbol)

    def build_chain(
        self, ctx: NodeContext
    ) -> Runnable[AnalyzeIndexInput, dict]:
        """Return a RunnableLambda that proposes indexes then fetches stats in parallel.

        Flow:
          1. ``propose_index`` → resolves the equity benchmark index set.
          2. Parallel ``get_and_calculate_stats`` for every equity benchmark
             index ticker returned by ``propose_index``.
          3. Parallel ``get_and_calculate_stats`` for every macro instrument
             in the ``'market_index'`` DB category (e.g. SOFR 3-Month).

        Args:
            ctx: Node context carrying thread/node/task identity.

        Returns:
            Runnable that accepts :class:`AnalyzeIndexInput` and produces a
            keyed dict with ``__index_results__`` and ``__equity_results__``.
        """
        async def _run(node_input: AnalyzeIndexInput) -> dict:
            # ----------------------------------------------------------------
            # Step 1: resolve equity benchmark indexes via propose_index.
            # ----------------------------------------------------------------
            propose_out: ProposeIndexOutput = (
                await self.run_task(
                    propose_index,
                    ctx,
                    ProposeIndexInput(stock_symbol=node_input.stock_symbol),
                )
            ).content

            if not propose_out.indexes:
                logger.error("[AI-004] propose_index returned no equity indexes.")

            # ----------------------------------------------------------------
            # Step 2: load macro instruments (SOFR etc.) from DB.
            # ----------------------------------------------------------------
            macro_instruments: list[MacroInstrument] = await load_macro_instruments(
                _INSTRUMENT_CATEGORY
            )
            if not macro_instruments:
                logger.error("[AI-001] No market-index instruments loaded from DB.")

            # ----------------------------------------------------------------
            # Step 3: fetch stats in parallel for equity indexes.
            # ----------------------------------------------------------------
            async def _fetch_equity(candidate: IndexCandidate) -> tuple[IndexEquityResult, dict] | None:
                """Fetch and compute stats for a single equity index; returns (result, df_split) or None on error."""
                try:
                    seq_out = await get_and_calculate_stats.run(
                        self.run_task,
                        ctx,
                        GetAndCalculateStatsInput(
                            symbol=candidate.ticker,
                            period=node_input.period,
                        ),
                    )
                    result = IndexEquityResult(
                        code=candidate.code,
                        ticker=candidate.ticker,
                        name=candidate.name,
                        zone=candidate.zone,
                        rows_upserted=seq_out.calculate_stats.rows_upserted,
                        granularity=seq_out.calculate_stats.granularity,
                        source=seq_out.calculate_stats.source,
                        from_cache=seq_out.get_stats.from_cache,
                        is_added=candidate.code == propose_out.added_code,
                    )
                    return result, seq_out.calculate_stats.df_split
                except Exception as exc:
                    logger.error(
                        "[AI-005] Equity index stats failed code=%r ticker=%r: %s",
                        candidate.code, candidate.ticker, exc,
                    )
                    return None

            # ----------------------------------------------------------------
            # Step 4: fetch stats in parallel for macro instruments.
            # ----------------------------------------------------------------
            async def _fetch_macro(inst: MacroInstrument) -> tuple[IndexInstrumentResult, dict] | None:
                """Fetch and compute stats for a single macro instrument; returns (result, df_split) or None on error."""
                try:
                    seq_out = await get_and_calculate_stats.run(
                        self.run_task,
                        ctx,
                        GetAndCalculateStatsInput(
                            symbol=inst.symbol,
                            period=node_input.period,
                        ),
                    )
                    result = IndexInstrumentResult(
                        code=inst.code,
                        symbol=inst.symbol,
                        label=inst.label,
                        region=inst.zone if inst.zone != "global" else None,
                        rows_upserted=seq_out.calculate_stats.rows_upserted,
                        granularity=seq_out.calculate_stats.granularity,
                        source=seq_out.calculate_stats.source,
                        from_cache=seq_out.get_stats.from_cache,
                    )
                    return result, seq_out.calculate_stats.df_split
                except Exception as exc:
                    logger.error("[AI-003] Index stats failed symbol=%r: %s", inst.symbol, exc)
                    return None

            equity_raw, macro_raw = await asyncio.gather(
                asyncio.gather(*[_fetch_equity(c) for c in propose_out.indexes]),
                asyncio.gather(*[_fetch_macro(inst) for inst in macro_instruments]),
            )

            equity_pairs = [r for r in equity_raw if r is not None]
            macro_pairs = [r for r in macro_raw if r is not None]
            equity_results = [p[0] for p in equity_pairs]
            macro_results = [p[0] for p in macro_pairs]

            if not equity_results and propose_out.indexes:
                logger.error("[AI-006] All equity index stats failed.")
            if not macro_results and macro_instruments:
                logger.error("[AI-002] All market-index instruments failed stats fetch.")

            # Equity indexes first, then macro instruments.
            df_splits = [
                {"symbol": p[0].ticker, "label": p[0].name, "df_split": p[1]}
                for p in equity_pairs if p[1]
            ] + [
                {"symbol": p[0].symbol, "label": p[0].label, "df_split": p[1]}
                for p in macro_pairs if p[1]
            ]

            return {
                "__equity_results__": equity_results,
                "__index_results__": macro_results,
                "__df_splits__": df_splits,
            }

        return RunnableLambda(_run)

    def build_output(self, results: dict) -> AnalyzeIndexOutput:
        """Compose node output from the parallel stats results.

        Args:
            results: Keyed task outputs from the chain.

        Returns:
            :class:`AnalyzeIndexOutput` with per-instrument and per-equity-index stats.
        """
        return AnalyzeIndexOutput(
            instruments=results.get("__index_results__", []),
            equity_indexes=results.get("__equity_results__", []),
            period=_STATS_PERIOD,
            df_splits=results.get("__df_splits__", []),
        )

    def get_state_updates(self, output: AnalyzeIndexOutput) -> dict[str, Any]:
        """No GraphState updates — output stored in node_executions via lifecycle.

        Args:
            output: Completed node output.

        Returns:
            Empty dict.
        """
        return {}


# Module-level callable registered with LangGraph StateGraph.
prepare_index_node = AnalyzeIndexNode()
