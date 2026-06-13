"""PrepareFuturesNode -- Workflow node that fetches and calculates OHLCV-based
stats for the configured futures-instrument universe (Gold, Silver, Crude,
Natural Gas, BTC, ETH, etc.) via the shared ``get_and_calculate_stats`` pipeline.

Hierarchy
---------
Thread
  └── prepare_futures (Workflow)
        └── get_and_calculate_stats (TaskSeq -> get_stats + calculate_stats)
            [× N instruments, parallel]

Node design
-----------
The node loads the ``'futures'`` category from ``fin_markets.macro_instruments``
at runtime and runs ``get_and_calculate_stats`` (``pipeline='futures'``) for
each instrument in parallel.  Each instrument's bars are processed through the
pandas_ta pipeline and upserted into the appropriate ``quant_*_stats`` table
determined by the stats-record instrument-type classifier
(e.g. ``precious_metal`` -> ``quant_precious_metal_stats``, ``commodity`` ->
``quant_commodity_stats``, ``crypto`` -> ``quant_crypto_stats``).

Predecessor
-----------
``query_node`` -- must be completed before ``prepare_futures`` starts.
Runs in parallel with ``prepare_peers``, ``prepare_macro_stats``,
``prepare_index``, ``prepare_news``, ``prepare_industry_news``,
``prepare_macro_news``, and ``prepare_options``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, ClassVar

from langchain_core.runnables import Runnable, RunnableLambda

from backend.db.postgres.queries.fin_markets_macro import (
    MacroInstrument,
    load_macro_instruments,
)
from backend.db.postgres.types import NodeType
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats import (
    GetAndCalculateStatsInput,
    get_and_calculate_stats,
)
from backend.langgraph.models.models import NodeContext
from backend.langgraph.models.node import BaseNode
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.prepare_futures.models import (
    FuturesInstrumentResult,
    PrepareFuturesInput,
    PrepareFuturesOutput,
)
from backend.langgraph.state import GraphState

logger = logging.getLogger(__name__)

_STATS_PERIOD: str = "1y"
_INSTRUMENT_CATEGORY: str = "futures"


class PrepareFuturesNode(BaseNode[PrepareFuturesInput, PrepareFuturesOutput]):
    """Workflow node: OHLCV stats for the configured futures universe."""

    node_name = "prepare_futures"
    node_type = NodeType.WORKFLOW
    display_name = "Prepare Futures"
    category = "Analysis"
    parallel_group: ClassVar[str] = "analyze_parallel"
    config_fields: ClassVar[list[dict]] = []
    tasks: ClassVar[list[NodeTask]] = [*get_and_calculate_stats.tasks]
    _prev_node_names: ClassVar[list[str]] = ["query_node"]

    async def build_input(self, state: GraphState) -> PrepareFuturesInput:
        """Return typed input with the configured stats period.

        Args:
            state: Current GraphState.

        Returns:
            :class:`PrepareFuturesInput` with the configured stats period.
        """
        return PrepareFuturesInput(period=_STATS_PERIOD)

    def build_chain(
        self, ctx: NodeContext
    ) -> Runnable[PrepareFuturesInput, dict[str, Any]]:
        """Run get_and_calculate_stats for every futures instrument in parallel.

        Args:
            ctx: Current node context carrying thread/node/task identity.

        Returns:
            Runnable that produces a keyed dict with ``instruments`` and
            ``df_splits``, consumed by :meth:`build_output`.
        """

        async def _run(node_input: PrepareFuturesInput) -> dict[str, Any]:
            instruments: list[MacroInstrument] = await load_macro_instruments(
                _INSTRUMENT_CATEGORY
            )
            if not instruments:
                logger.warning(
                    "[PF-001] No futures instruments loaded from DB "
                    "(category=%r); skipping prepare_futures.",
                    _INSTRUMENT_CATEGORY,
                )
                return {"instruments": [], "df_splits": []}

            async def _fetch_one(
                inst: MacroInstrument,
            ) -> tuple[FuturesInstrumentResult, dict[str, Any]] | None:
                try:
                    seq_out = await get_and_calculate_stats.run(
                        self.run_task,
                        ctx,
                        GetAndCalculateStatsInput(
                            symbol=inst.symbol,
                            period=node_input.period,
                            pipeline="futures",
                        ),
                    )
                    calc = seq_out.calculate_stats
                    result = FuturesInstrumentResult(
                        code=inst.code,
                        symbol=inst.symbol,
                        label=inst.label,
                        currency_code=inst.currency_code,
                        rows_upserted=int(getattr(calc, "rows_upserted", 0) or 0),
                        granularity=getattr(calc, "granularity", "") or "",
                        source=getattr(calc, "source", "") or "",
                        from_cache=bool(seq_out.get_stats.from_cache),
                    )
                    return result, getattr(calc, "df_split", {}) or {}
                except Exception as exc:
                    logger.error(
                        "[PF-002] futures stats failed symbol=%r: %s", inst.symbol, exc,
                    )
                    return None

            raw = await asyncio.gather(*[_fetch_one(inst) for inst in instruments])
            pairs = [r for r in raw if r is not None]
            results = [p[0] for p in pairs]
            df_splits = [
                {"symbol": p[0].symbol, "label": p[0].label, "df_split": p[1]}
                for p in pairs
                if p[1]
            ]
            return {"instruments": results, "df_splits": df_splits}

        return RunnableLambda(_run)

    def build_output(self, results: dict[str, Any]) -> PrepareFuturesOutput:
        """Compose node output from the parallel pipeline results.

        Args:
            results: Keyed task outputs from the chain.

        Returns:
            :class:`PrepareFuturesOutput` with per-instrument results and any
            ``df_split`` payloads.
        """
        return PrepareFuturesOutput(
            instruments=results.get("instruments", []),
            period=results.get("period", _STATS_PERIOD) or _STATS_PERIOD,
            df_splits=results.get("df_splits", []),
        )

    def get_state_updates(self, output: PrepareFuturesOutput) -> dict[str, Any]:
        """No GraphState updates -- data flows via DB."""
        return {}


# Module-level callable registered with LangGraph StateGraph.
prepare_futures_node = PrepareFuturesNode()
