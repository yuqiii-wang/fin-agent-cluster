"""PrepareFundamentalsNode -- Workflow node for fetching and aggregating
fundamental data (income statement / balance sheet / cash flow / key metrics)
for the queried stock.

Currently implemented as a skeleton (empty).  Downstream this node will:
  * fetch and calculate fundamentals for the stock
  * aggregate key metrics and valuation multiples

Graph topology
--------------
Thread
  └── prepare_fundamentals  (Workflow, currently empty skeleton)

Predecessor
-----------
``query_node``.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from langchain_core.runnables import Runnable, RunnableLambda

from backend.db.postgres.types import NodeType
from backend.langgraph.models.node import BaseNode
from backend.langgraph.nodes.prepare_fundamentals.models import (
    PrepareFundamentalsInput,
    PrepareFundamentalsOutput,
)
from backend.langgraph.state import GraphState

logger = logging.getLogger(__name__)


class PrepareFundamentalsNode(BaseNode[PrepareFundamentalsInput, PrepareFundamentalsOutput]):
    """Workflow node: fetches and aggregates fundamental data for the queried stock."""

    node_name = "prepare_fundamentals"
    node_type = NodeType.WORKFLOW
    display_name = "Prepare Fundamentals"
    category = "Analysis"
    parallel_group: ClassVar[str] = "analyze_parallel"
    view_type = "Markdown"
    tasks: ClassVar[list] = []
    _prev_node_names: ClassVar[list[str]] = ["query_node"]

    async def build_input(self, state: GraphState) -> PrepareFundamentalsInput:
        """Construct node input -- currently empty.

        Args:
            state: Current GraphState.

        Returns:
            Empty :class:`PrepareFundamentalsInput`.
        """
        return PrepareFundamentalsInput()

    def build_chain(
        self, ctx,
    ) -> Runnable[PrepareFundamentalsInput, dict]:
        """Return a no-op RunnableLambda -- node is intentionally empty.

        Args:
            ctx: Node context carrying thread/node/task identity.

        Returns:
            Runnable that returns an empty dict.
        """
        async def _run(node_input: PrepareFundamentalsInput) -> dict:
            return {}

        return RunnableLambda(_run)

    def build_output(self, results: dict) -> PrepareFundamentalsOutput:
        """Compose node output -- currently empty.

        Args:
            results: Keyed task outputs from the chain.

        Returns:
            Empty :class:`PrepareFundamentalsOutput`.
        """
        return PrepareFundamentalsOutput()

    def get_state_updates(self, output: PrepareFundamentalsOutput) -> dict[str, Any]:
        """No GraphState updates yet.

        Args:
            output: Completed node output.

        Returns:
            Empty dict.
        """
        return {}


prepare_fundamentals_node = PrepareFundamentalsNode()
