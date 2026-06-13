"""PrepareFundamentalsNode -- Workflow node that fetches fundamental data for the queried
equity symbol (e.g. income statement, balance sheet, cash flow, key ratios).

Hierarchy
---------
Thread
  └── prepare_fundamentals  (Workflow)
        └── get_and_calculate_stats  (TaskSeq -> get_stats + calculate_stats)

Flow
----
1. Reads the confirmed ``stock_name`` from ``query_node``'s persisted output.
2. Runs ``get_and_calculate_stats`` to fetch 2 years of daily OHLCV bars,
   compute technical indicators, and upsert rows to ``quant_stats``.

Predecessor
-----------
``query_node`` -- must be completed before ``prepare_fundamentals`` starts.
Runs in parallel with ``prepare_peers``, ``prepare_macro_stats``, ``prepare_index``,
``prepare_news``, ``prepare_industry_news``, ``prepare_macro_news``,
``prepare_options``, and ``prepare_futures``.
"""

from __future__ import annotations

from typing import Any, ClassVar

from langchain_core.runnables import Runnable, RunnableLambda

from backend.db.postgres.types import NodeType
from backend.langgraph.lifecycle import read_node_output
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats import (
    GetAndCalculateStatsInput,
    get_and_calculate_stats,
)
from backend.langgraph.models.models import NodeContext, TaskOutput
from backend.langgraph.models.node import BaseNode
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.prepare_fundamentals.models import (
    PrepareFundamentalsInput,
    PrepareFundamentalsOutput,
)
from backend.langgraph.state import GraphState

_STATS_PERIOD = "2y"

_STATS_KEY = "get_and_calculate_stats"


class PrepareFundamentalsNode(BaseNode[PrepareFundamentalsInput, PrepareFundamentalsOutput]):
    """Workflow node: fetches OHLCV stats and technical indicators for the queried symbol."""

    node_name = "prepare_fundamentals"
    node_type = NodeType.WORKFLOW
    display_name = "Prepare Fundamentals"
    category = "Analysis"
    parallel_group: ClassVar[str] = "analyze_parallel"
    config_fields: ClassVar[list[dict]] = []
    view_type = "Stats"
    stats_views: ClassVar[list[str]] = []
    tasks: ClassVar[list[NodeTask]] = [*get_and_calculate_stats.tasks]
    _prev_node_names: ClassVar[list[str]] = ["query_node"]

    async def build_input(self, state: GraphState) -> PrepareFundamentalsInput:
        """Read stock_name from query_node's completed node_executions row.

        Args:
            state: Current GraphState.

        Returns:
            :class:`PrepareFundamentalsInput` with the resolved stock symbol.
        """
        query_node_id = self._find_node_id_by_name(state, "query_node")
        stock_symbol = ""
        if query_node_id:
            output = await read_node_output(query_node_id)
            stock_symbol = output.get("stock_name", "")
        return PrepareFundamentalsInput(stock_symbol=stock_symbol)

    def build_chain(
        self, ctx: NodeContext
    ) -> Runnable[PrepareFundamentalsInput, dict]:
        """Run get_and_calculate_stats for the confirmed symbol.

        Args:
            ctx: Node context carrying thread/node/task identity.

        Returns:
            Runnable that accepts :class:`PrepareFundamentalsInput` and produces a
            keyed dict with ``_STATS_KEY``.
        """
        async def _run(node_input: PrepareFundamentalsInput) -> dict[str, Any]:
            seq_out = await get_and_calculate_stats.run(
                self.run_task,
                ctx,
                GetAndCalculateStatsInput(symbol=node_input.stock_symbol, period=_STATS_PERIOD),
            )
            return {_STATS_KEY: seq_out, "symbol": node_input.stock_symbol}

        return RunnableLambda(_run)  # type: ignore[arg-type]

    def build_output(self, results: dict[str, Any]) -> PrepareFundamentalsOutput:
        """Compose node output from stats results.

        Args:
            results: Keyed outputs from the chain.

        Returns:
            :class:`PrepareFundamentalsOutput` with the resolved symbol.
        """
        return PrepareFundamentalsOutput(symbol=results.get("symbol", ""))

    def get_state_updates(self, output: PrepareFundamentalsOutput) -> dict[str, Any]:
        """No GraphState updates -- data flows via DB."""
        return {}


prepare_fundamentals_node = PrepareFundamentalsNode()
