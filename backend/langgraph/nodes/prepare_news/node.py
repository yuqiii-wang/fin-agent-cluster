"""PrepareNewsNode -- Workflow node for news fetch and digest.

Currently implemented as a skeleton (empty).  Downstream this node will:
  * fetch latest news for the queried stock
  * digest articles via LLM and upsert to news_stats

Graph topology
--------------
Thread
  └── prepare_news  (Workflow, currently empty skeleton)

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
from backend.langgraph.nodes.prepare_news.models import (
    PrepareNewsInput,
    PrepareNewsOutput,
)
from backend.langgraph.state import GraphState

logger = logging.getLogger(__name__)


class PrepareNewsNode(BaseNode[PrepareNewsInput, PrepareNewsOutput]):
    """Workflow node: fetches and digests news for the queried stock."""

    node_name = "prepare_news"
    node_type = NodeType.WORKFLOW
    display_name = "Prepare News"
    category = "Analysis"
    parallel_group: ClassVar[str] = "analyze_parallel"
    config_fields: ClassVar[list[dict]] = [
        {
            "key": "human_in_the_loop",
            "label": "Review news digest",
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

    async def build_input(self, state: GraphState) -> PrepareNewsInput:
        """Construct node input -- currently empty.

        Args:
            state: Current GraphState.

        Returns:
            Empty :class:`PrepareNewsInput`.
        """
        return PrepareNewsInput()

    def build_chain(
        self, ctx,
    ) -> Runnable[PrepareNewsInput, dict]:
        """Return a no-op RunnableLambda -- node is intentionally empty.

        Args:
            ctx: Node context carrying thread/node/task identity.

        Returns:
            Runnable that returns an empty dict.
        """
        async def _run(node_input: PrepareNewsInput) -> dict:
            return {}

        return RunnableLambda(_run)

    def build_output(self, results: dict) -> PrepareNewsOutput:
        """Compose node output -- currently empty.

        Args:
            results: Keyed task outputs from the chain.

        Returns:
            Empty :class:`PrepareNewsOutput`.
        """
        return PrepareNewsOutput()

    def get_state_updates(self, output: PrepareNewsOutput) -> dict[str, Any]:
        """No GraphState updates yet.

        Args:
            output: Completed node output.

        Returns:
            Empty dict.
        """
        return {}


prepare_news_node = PrepareNewsNode()
