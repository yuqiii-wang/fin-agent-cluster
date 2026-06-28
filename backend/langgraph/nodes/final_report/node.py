"""FinalReportNode -- Terminal node that assembles the final analysis report.

Currently implemented as a skeleton (empty).  Downstream this node will:
  * collect outputs from every upstream analysis node
  * synthesize them into a cohesive trading / investment report
  * emit the final report payload for the UI

Graph topology (final)
----------------------
  ... analysis parallel group ... -> final_report -> END

Predecessors
------------
``load_peers_stats``, ``prepare_macro_stats``, ``prepare_index``,
``prepare_news``, ``prepare_industry_news``, ``prepare_macro_news``,
``prepare_options``, ``prepare_futures``.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import Runnable, RunnableLambda

from backend.db.postgres.types import NodeType
from backend.langgraph.models.node import BaseNode
from backend.langgraph.nodes.final_report.models import (
    FinalReportInput,
    FinalReportOutput,
)
from backend.langgraph.state import GraphState

logger = logging.getLogger(__name__)


class FinalReportNode(BaseNode[FinalReportInput, FinalReportOutput]):
    """Workflow node: assembles the final analysis report."""

    node_name = "final_report"
    node_type = NodeType.WORKFLOW
    display_name = "Final Report"
    category = "Report"
    config_fields: list[dict] = []
    view_type = "Markdown"
    tasks: list = []
    _prev_node_names: list[str] = [
        "load_peers_stats",
        "prepare_macro_stats",
        "prepare_index",
        "prepare_news",
        "prepare_industry_news",
        "prepare_macro_news",
        "load_symbol_stats",
        "prepare_options",
        "prepare_futures",
        "prepare_fundamentals",
    ]

    async def build_input(self, state: GraphState) -> FinalReportInput:
        """Construct node input -- currently empty.

        Args:
            state: Current GraphState.

        Returns:
            Empty :class:`FinalReportInput`.
        """
        return FinalReportInput()

    def build_chain(
        self,
        ctx,
    ) -> Runnable[FinalReportInput, dict]:
        """Return a no-op RunnableLambda -- node is intentionally empty.

        Args:
            ctx: Node context carrying thread/node/task identity.

        Returns:
            Runnable that returns an empty dict.
        """
        async def _run(node_input: FinalReportInput) -> dict:
            return {}

        return RunnableLambda(_run)

    def build_output(self, results: dict) -> FinalReportOutput:
        """Compose node output -- currently empty.

        Args:
            results: Keyed task outputs from the chain.

        Returns:
            Empty :class:`FinalReportOutput`.
        """
        return FinalReportOutput()

    def get_state_updates(self, output: FinalReportOutput) -> dict[str, Any]:
        """No GraphState updates yet.

        Args:
            output: Completed node output.

        Returns:
            Empty dict.
        """
        return {}


final_report_node = FinalReportNode()
