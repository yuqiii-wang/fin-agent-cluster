"""PrepareIndustryNewsNode -- Workflow node for industry/sector news fetch and digest.

Currently implemented as a skeleton (empty).  Downstream this node will:
  * propose industry-specific news topics via LLM
  * fetch and digest industry/sector news for the queried stock

Graph topology
--------------
Thread
  └── prepare_industry_news  (Workflow, currently empty skeleton)

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
from backend.langgraph.nodes.prepare_industry_news.models import (
    PrepareIndustryNewsInput,
    PrepareIndustryNewsOutput,
)
from backend.langgraph.state import GraphState

logger = logging.getLogger(__name__)


class PrepareIndustryNewsNode(BaseNode[PrepareIndustryNewsInput, PrepareIndustryNewsOutput]):
    """Workflow node: fetches and digests industry/sector news for the queried stock."""

    node_name = "prepare_industry_news"
    node_type = NodeType.WORKFLOW
    display_name = "Prepare Industry News"
    category = "Analysis"
    parallel_group: ClassVar[str] = "analyze_parallel"
    config_fields: ClassVar[list[dict]] = [
        {
            "key": "human_in_the_loop",
            "label": "Review industry news digest",
            "type": "boolean",
            "description": "Pause after news is fetched and digested; wait for your approval.",
        },
        {
            "key": "lookback_days",
            "label": "Lookback days",
            "type": "number",
            "description": "How many calendar days of news history to fetch (default 7).",
        },
    ]
    view_type = "Markdown"
    tasks: ClassVar[list] = []
    _prev_node_names: ClassVar[list[str]] = ["query_node"]

    async def build_input(self, state: GraphState) -> PrepareIndustryNewsInput:
        """Construct node input -- currently empty.

        Args:
            state: Current GraphState.

        Returns:
            Empty :class:`PrepareIndustryNewsInput`.
        """
        return PrepareIndustryNewsInput()

    def build_chain(
        self, ctx,
    ) -> Runnable[PrepareIndustryNewsInput, dict]:
        """Return a no-op RunnableLambda -- node is intentionally empty.

        Args:
            ctx: Node context carrying thread/node/task identity.

        Returns:
            Runnable that returns an empty dict.
        """
        async def _run(node_input: PrepareIndustryNewsInput) -> dict:
            return {}

        return RunnableLambda(_run)

    def build_output(self, results: dict) -> PrepareIndustryNewsOutput:
        """Compose node output -- currently empty.

        Args:
            results: Keyed task outputs from the chain.

        Returns:
            Empty :class:`PrepareIndustryNewsOutput`.
        """
        return PrepareIndustryNewsOutput()

    def get_state_updates(self, output: PrepareIndustryNewsOutput) -> dict[str, Any]:
        """No GraphState updates yet.

        Args:
            output: Completed node output.

        Returns:
            Empty dict.
        """
        return {}


prepare_industry_news_node = PrepareIndustryNewsNode()
