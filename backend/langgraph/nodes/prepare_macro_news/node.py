"""PrepareMacroNewsNode -- Workflow node for macro-economic news fetch and digest.

Currently implemented as a skeleton (empty).  Downstream this node will:
  * fetch and digest macro-economic news (Fed policy, inflation, GDP, rates, etc.)

Graph topology
--------------
Thread
  └── prepare_macro_news  (Workflow, currently empty skeleton)

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
from backend.langgraph.nodes.prepare_macro_news.models import (
    PrepareMacroNewsInput,
    PrepareMacroNewsOutput,
)
from backend.langgraph.state import GraphState

logger = logging.getLogger(__name__)


class PrepareMacroNewsNode(BaseNode[PrepareMacroNewsInput, PrepareMacroNewsOutput]):
    """Workflow node: fetches and digests macro-economic news."""

    node_name = "prepare_macro_news"
    node_type = NodeType.WORKFLOW
    display_name = "Prepare Macro News"
    category = "Analysis"
    parallel_group: ClassVar[str] = "analyze_parallel"
    config_fields: ClassVar[list[dict]] = [
        {
            "key": "human_in_the_loop",
            "label": "Review macro news digest",
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

    async def build_input(self, state: GraphState) -> PrepareMacroNewsInput:
        """Construct node input -- currently empty.

        Args:
            state: Current GraphState.

        Returns:
            Empty :class:`PrepareMacroNewsInput`.
        """
        return PrepareMacroNewsInput()

    def build_chain(
        self, ctx,
    ) -> Runnable[PrepareMacroNewsInput, dict]:
        """Return a no-op RunnableLambda -- node is intentionally empty.

        Args:
            ctx: Node context carrying thread/node/task identity.

        Returns:
            Runnable that returns an empty dict.
        """
        async def _run(node_input: PrepareMacroNewsInput) -> dict:
            return {}

        return RunnableLambda(_run)

    def build_output(self, results: dict) -> PrepareMacroNewsOutput:
        """Compose node output -- currently empty.

        Args:
            results: Keyed task outputs from the chain.

        Returns:
            Empty :class:`PrepareMacroNewsOutput`.
        """
        return PrepareMacroNewsOutput()

    def get_state_updates(self, output: PrepareMacroNewsOutput) -> dict[str, Any]:
        """No GraphState updates yet.

        Args:
            output: Completed node output.

        Returns:
            Empty dict.
        """
        return {}


prepare_macro_news_node = PrepareMacroNewsNode()
