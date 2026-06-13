"""PreparePeersNode -- Workflow node that proposes industry peer companies for a target stock.

Hierarchy
---------
Thread
  └── prepare_peers  (Workflow)
        └── propose_peers   (@task -> Celery Streaming)   [×1]

Node design
-----------
Reads ``stock_name`` from the ``query_node`` output, then runs the
``propose_peers`` LLM streaming task to identify 3-6 peer or comparable
companies for the target stock.

The output (``proposed_peers``) is persisted to ``fin_agents.node_executions``
and made available to downstream nodes.

Predecessor
-----------
``query_node`` -- must be completed before ``prepare_peers`` starts.
Runs in parallel with ``prepare_macro_stats``, ``prepare_index``,
``prepare_news``, ``prepare_industry_news``, ``prepare_macro_news``,
``prepare_options``, and ``prepare_futures``.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from langchain_core.runnables import Runnable, RunnableLambda

from backend.db.postgres.types import NodeType
from backend.langgraph.lifecycle import read_node_output
from backend.langgraph.models.models import NodeContext
from backend.langgraph.models.node import BaseNode
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.prepare_peers.models.input import AnalyzePeersInput
from backend.langgraph.nodes.prepare_peers.models.output import AnalyzePeersOutput
from backend.langgraph.nodes.prepare_peers.tasks.propose_peers import (
    ProposePeersInput,
    propose_peers,
)
from backend.langgraph.state import GraphState

logger = logging.getLogger(__name__)


class PreparePeersNode(BaseNode[AnalyzePeersInput, AnalyzePeersOutput]):
    """Workflow node: proposes peer companies for a target stock via LLM streaming."""

    node_name = "prepare_peers"
    node_type = NodeType.WORKFLOW
    display_name = "Prepare Peers"
    category = "Analysis"
    parallel_group: ClassVar[str] = "analyze_parallel"
    config_fields: ClassVar[list[dict]] = [
        {
            "key": "human_in_the_loop",
            "label": "Review peer selection",
            "type": "boolean",
            "description": "Pause after peers are proposed; wait for your approval.",
        },
    ]
    view_type = "Json"
    tasks: ClassVar[list[NodeTask]] = [propose_peers]
    _prev_node_names: ClassVar[list[str]] = ["query_node"]

    async def build_input(self, state: GraphState) -> AnalyzePeersInput:
        """Read stock_name from query_node's completed node_executions row.

        Args:
            state: Current GraphState.

        Returns:
            Typed :class:`AnalyzePeersInput` populated from the PG replica.
        """
        query_node_id = self._find_node_id_by_name(state, "query_node")
        stock_name = ""
        if query_node_id:
            output = await read_node_output(query_node_id)
            stock_name = output.get("stock_name", "")
        else:
            logger.error("[AP-001] query_node output unavailable; stock_name will be empty.")
        return AnalyzePeersInput(stock_name=stock_name)

    def build_chain(
        self, ctx: NodeContext
    ) -> Runnable[AnalyzePeersInput, dict]:
        """Return a RunnableLambda that runs the propose_peers streaming task.

        Args:
            ctx: Node context carrying thread/node/task identity.

        Returns:
            Runnable that accepts :class:`AnalyzePeersInput` and returns a keyed
            dict with ``propose_peers`` task output.
        """
        async def _run(node_input: AnalyzePeersInput) -> dict:
            result = await self.run_task(
                propose_peers,
                ctx,
                ProposePeersInput(stock_name=node_input.stock_name),
            )
            return {"propose_peers": result}

        return RunnableLambda(_run)

    def build_output(self, results: dict) -> AnalyzePeersOutput:
        """Compose node output from the propose_peers task result.

        Args:
            results: Keyed task outputs from the chain.

        Returns:
            :class:`AnalyzePeersOutput` with the proposed peer tickers.
        """
        task_output = results.get("propose_peers")
        if task_output is None:
            logger.error("[AP-002] propose_peers task output missing from results.")
            return AnalyzePeersOutput()
        return AnalyzePeersOutput(proposed_peers=task_output.content.peers)

    def get_state_updates(self, output: AnalyzePeersOutput) -> dict[str, Any]:
        """No GraphState updates -- output stored in node_executions via lifecycle.

        Args:
            output: Completed node output.

        Returns:
            Empty dict.
        """
        return {}


# Module-level callable registered with LangGraph StateGraph.
prepare_peers_node = PreparePeersNode()
