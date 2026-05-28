"""PrepareFundamentalsNode — Workflow node that fetches fundamental data for the queried
equity symbol (e.g. income statement, balance sheet, cash flow, key ratios).

Hierarchy
---------
Thread
  └── prepare_fundamentals  (Workflow)

Node design
-----------
(Empty — implementation pending.)

Predecessor
-----------
``query_node`` — must be completed before ``prepare_fundamentals`` starts.
Runs in parallel with ``prepare_peers``, ``prepare_macro_stats``, ``prepare_index``,
``prepare_news``, ``prepare_industry_news``, ``prepare_macro_news``, and
``prepare_derivatives``.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from langchain_core.runnables import Runnable, RunnableLambda

from backend.db.postgres.types import NodeType
from backend.langgraph.models.models import NodeContext
from backend.langgraph.models.node import BaseNode
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.prepare_fundamentals.models import (
    PrepareFundamentalsInput,
    PrepareFundamentalsOutput,
)
from backend.langgraph.state import GraphState

logger = logging.getLogger(__name__)


class PrepareFundamentalsNode(BaseNode[PrepareFundamentalsInput, PrepareFundamentalsOutput]):
    """Workflow node: fetches fundamental data for the queried symbol."""

    node_name = "prepare_fundamentals"
    node_type = NodeType.WORKFLOW
    display_name = "Prepare Fundamentals"
    category = "Analysis"
    parallel_group: ClassVar[str] = "analyze_parallel"
    config_fields: ClassVar[list[dict]] = []
    view_type = "Stats"
    stats_views: ClassVar[list[str]] = []
    tasks: ClassVar[list[NodeTask]] = []
    _prev_node_names: ClassVar[list[str]] = ["query_node"]

    async def build_input(self, state: GraphState) -> PrepareFundamentalsInput:
        """Construct node input — reads stock_symbol from query_node output.

        Args:
            state: Current GraphState.

        Returns:
            :class:`PrepareFundamentalsInput` with the resolved stock symbol.
        """
        return PrepareFundamentalsInput()

    def build_chain(
        self, ctx: NodeContext
    ) -> Runnable[PrepareFundamentalsInput, dict]:
        """Return a RunnableLambda that fetches fundamentals data for the queried symbol.

        Args:
            ctx: Node context carrying thread/node/task identity.

        Returns:
            Runnable that accepts :class:`PrepareFundamentalsInput` and produces a
            keyed dict (empty for now).
        """
        async def _run(node_input: PrepareFundamentalsInput) -> dict[str, Any]:
            return PrepareFundamentalsOutput().model_dump()

        return RunnableLambda(_run)  # type: ignore[arg-type]


prepare_fundamentals_node = PrepareFundamentalsNode()
