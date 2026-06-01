"""AnalyzeMacroNode — Workflow node that fetches and calculates stats for
macro instruments (gold, silver, natural gas, crude oil, bitcoin, ethereum).

Hierarchy
---------
Thread
  └── analyze_economics  (Workflow)
        └── get_and_calculate_stats  (TaskSeq → get_stats + calculate_stats)  [xN instruments, parallel]

Node design
-----------
The node loads the ``'macro'`` category from ``fin_markets.macro_instruments``
(gold ``GC=F``, silver ``SI=F``, natural gas ``NG=F``, crude oil ``CL=F``,
bitcoin ``BTC-USD``, ethereum ``ETH-USD``) at
runtime and runs ``get_and_calculate_stats`` for each instrument in parallel.
No correlation analysis is performed.

Predecessor
-----------
``query_node`` — must be completed before ``analyze_economics`` starts.
Runs in parallel with ``prepare_peers``, ``prepare_macro_stats``, and ``prepare_index``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, ClassVar

from langchain_core.runnables import Runnable, RunnableLambda

from backend.db.postgres.types import NodeType
from backend.db.postgres.queries.fin_markets_macro import load_macro_instruments, MacroInstrument
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats import (
    get_and_calculate_stats,
    GetAndCalculateStatsInput,
)
from backend.langgraph.models.models import NodeContext
from backend.langgraph.models.node import BaseNode
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.prepare_macro_stats.models import (
    AnalyzeEconomicsInput,
    AnalyzeEconomicsOutput,
    EconomicsInstrumentResult,
)
from backend.langgraph.state import GraphState
from backend.quant.stats import STATS_VIEW_TYPE

logger = logging.getLogger(__name__)

_STATS_PERIOD: str = "2y"
_INSTRUMENT_CATEGORY: str = "macro"


class AnalyzeMacroNode(BaseNode[AnalyzeEconomicsInput, AnalyzeEconomicsOutput]):
    """Workflow node: fetches and calculates stats for macro commodity instruments."""

    node_name = "prepare_macro_stats"
    node_type = NodeType.WORKFLOW
    display_name = "Analyze Macro"
    category = "Analysis"
    parallel_group: ClassVar[str] = "analyze_parallel"
    config_fields: ClassVar[list[dict]] = [
        {
            "key": "human_in_the_loop",
            "label": "Review macro analysis",
            "type": "boolean",
            "description": "Pause after macro-economic instrument stats are computed; wait for your approval.",
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
            "description": "Controls how much historical data is analysed for macro instruments.",
        },
    ]
    view_type = "Stats"
    stats_views = [STATS_VIEW_TYPE.STACK_CANDLE_STICK.value]
    tasks: ClassVar[list[NodeTask]] = [*get_and_calculate_stats.tasks]
    _prev_node_names: ClassVar[list[str]] = ["query_node"]

    async def build_input(self, state: GraphState) -> AnalyzeEconomicsInput:
        """Construct node input — uses the default stats period.

        Args:
            state: Current GraphState.

        Returns:
            :class:`AnalyzeEconomicsInput` with the configured stats period.
        """
        return AnalyzeEconomicsInput(period=_STATS_PERIOD)

    def build_chain(
        self, ctx: NodeContext
    ) -> Runnable[AnalyzeEconomicsInput, dict]:
        """Return a RunnableLambda that fetches stats for all economics instruments in parallel.

        Args:
            ctx: Node context carrying thread/node/task identity.

        Returns:
            Runnable that accepts :class:`AnalyzeEconomicsInput` and produces a
            keyed dict with ``__economics_results__`` summary.
        """
        async def _run(node_input: AnalyzeEconomicsInput) -> dict:
            instruments: list[MacroInstrument] = await load_macro_instruments(_INSTRUMENT_CATEGORY)
            if not instruments:
                logger.error("[AE-001] No economics instruments loaded from DB.")

            async def _fetch_one(inst: MacroInstrument) -> tuple[EconomicsInstrumentResult, dict] | None:
                """Fetch and compute stats for a single instrument; returns None on error."""
                try:
                    seq_out = await get_and_calculate_stats.run(
                        self.run_task,
                        ctx,
                        GetAndCalculateStatsInput(
                            symbol=inst.symbol,
                            period=node_input.period,
                        ),
                    )
                    result = EconomicsInstrumentResult(
                        code=inst.code,
                        symbol=inst.symbol,
                        label=inst.label,
                        rows_upserted=seq_out.calculate_stats.rows_upserted,
                        granularity=seq_out.calculate_stats.granularity,
                        source=seq_out.calculate_stats.source,
                        from_cache=seq_out.get_stats.from_cache,
                    )
                    return result, seq_out.calculate_stats.df_split
                except Exception as exc:
                    logger.error("[AE-003] Economics stats failed symbol=%r: %s", inst.symbol, exc)
                    return None

            raw_results = await asyncio.gather(*[_fetch_one(inst) for inst in instruments])
            pairs = [r for r in raw_results if r is not None]
            results = [p[0] for p in pairs]
            df_splits = [
                {"symbol": p[0].symbol, "label": p[0].label, "df_split": p[1]}
                for p in pairs
                if p[1]
            ]

            if not results and instruments:
                logger.error("[AE-002] All economics instruments failed stats fetch.")

            return {"__economics_results__": results, "__df_splits__": df_splits}

        return RunnableLambda(_run)

    def build_output(self, results: dict) -> AnalyzeEconomicsOutput:
        """Compose node output from the parallel stats results.

        Args:
            results: Keyed task outputs from the chain.

        Returns:
            :class:`AnalyzeEconomicsOutput` with per-instrument stats.
        """
        instrument_results: list[EconomicsInstrumentResult] = results.get(
            "__economics_results__", []
        )
        df_splits: list[dict] = results.get("__df_splits__", [])
        return AnalyzeEconomicsOutput(
            instruments=instrument_results,
            period=_STATS_PERIOD,
            df_splits=df_splits,
        )

    def get_state_updates(self, output: AnalyzeEconomicsOutput) -> dict[str, Any]:
        """No GraphState updates — output stored in node_executions via lifecycle.

        Args:
            output: Completed node output.

        Returns:
            Empty dict.
        """
        return {}


# Module-level callable registered with LangGraph StateGraph.
prepare_macro_stats_node = AnalyzeMacroNode()
