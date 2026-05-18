"""Regional analyze nodes — ApacAnalyzeNode, EmeaAnalyzeNode, AmerAnalyzeNode.

Topology (one of these runs per query, selected by UTC business hour):

  query_node
    │
    ├──[UTC 00-08]──► apac_analyze_node ──┐
    ├──[UTC 08-16]──► emea_analyze_node ──┼──► research_subgraph
    └──[UTC 16-24]──► amer_analyze_node ──┘

All three nodes share the same structure (single regional task, identical chain
pattern, same state write).  They differ only in which ``NodeTask`` they bind
and what ``region`` label is injected into the input.

Each node:
    * Reads query_node output from ``fin_agents.node_executions`` via the PG
      replica (``read_node_output``).  No state blobs are used.
    * Injects its own ``region`` string into ``RegionalAnalyzeInput``.
    * Writes execution output to ``fin_agents.node_executions`` via lifecycle.
      Downstream nodes read this output via ``read_node_output(node_id)``.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from langchain_core.runnables import Runnable, RunnableLambda

from backend.db.postgres.types import NodeType
from backend.langgraph.lifecycle import read_node_output
from backend.langgraph.models.node import BaseNode
from backend.langgraph.models.models import NodeContext, TaskOutput
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.regional_analyze_nodes.models import (
    RegionalAnalyzeInput,
    RegionalAnalyzeOutput,
)
from backend.langgraph.nodes.regional_analyze_nodes.tasks import apac_analyze, emea_analyze, amer_analyze
from backend.langgraph.state import GraphState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------


class _RegionalBaseNode(BaseNode[RegionalAnalyzeInput, RegionalAnalyzeOutput]):
    """Abstract base for APAC / EMEA / AMER analyze nodes.

    Subclasses set ``node_name``, ``tasks``, and ``_region_task``.
    """

    node_type: ClassVar[NodeType] = NodeType.WORKFLOW
    _region_task: ClassVar[NodeTask]
    _prev_node_names: ClassVar[list[str]] = ["query_node"]

    async def build_input(self, state: GraphState) -> RegionalAnalyzeInput:
        """Read query_node output from the PG replica and inject the region label.

        Reads the output stored by query_node in ``fin_agents.node_executions``
        via ``read_node_output``, which always queries the replica.
        """
        query_node_id = self._find_node_id_by_name(state, "query_node")
        qa: dict = {}
        if query_node_id:
            qa = await read_node_output(query_node_id)
        region = self.node_name.replace("_analyze_node", "")
        return RegionalAnalyzeInput(
            intent=qa.get("intent", ""),
            symbols=qa.get("symbols", []),
            filters=qa.get("filters", {}),
            query_time=qa.get("query_time", ""),
            region=region,
        )

    def build_chain(self, ctx: NodeContext) -> Runnable[RegionalAnalyzeInput, dict[str, TaskOutput]]:
        """Chain: single regional task wrapped as a RunnableLambda."""
        task = self._region_task
        return (
            self._task_as_runnable(task, ctx)
            | RunnableLambda(lambda r: {task.name: r})
        )

    def build_output(self, results: dict[str, TaskOutput]) -> RegionalAnalyzeOutput:
        """Return the regional task's typed content."""
        return results[self._region_task.name].content

    def get_state_updates(self, output: RegionalAnalyzeOutput) -> dict[str, Any]:
        """No state updates — output stored in node_executions via lifecycle."""
        return {}


# ---------------------------------------------------------------------------
# Concrete regional nodes
# ---------------------------------------------------------------------------


class ApacAnalyzeNode(_RegionalBaseNode):
    """Regional analyze node for the APAC session (UTC 00:00-08:00)."""

    node_name: ClassVar[str] = "apac_analyze_node"
    tasks: ClassVar[list[NodeTask]] = [apac_analyze]
    _region_task: ClassVar[NodeTask] = apac_analyze


class EmeaAnalyzeNode(_RegionalBaseNode):
    """Regional analyze node for the EMEA session (UTC 08:00-16:00)."""

    node_name: ClassVar[str] = "emea_analyze_node"
    tasks: ClassVar[list[NodeTask]] = [emea_analyze]
    _region_task: ClassVar[NodeTask] = emea_analyze


class AmerAnalyzeNode(_RegionalBaseNode):
    """Regional analyze node for the AMER session (UTC 16:00-24:00)."""

    node_name: ClassVar[str] = "amer_analyze_node"
    tasks: ClassVar[list[NodeTask]] = [amer_analyze]
    _region_task: ClassVar[NodeTask] = amer_analyze


# Module-level callables registered with LangGraph StateGraph.
apac_analyze_node = ApacAnalyzeNode()
emea_analyze_node = EmeaAnalyzeNode()
amer_analyze_node = AmerAnalyzeNode()



# ---------------------------------------------------------------------------
# Concrete regional nodes
# ---------------------------------------------------------------------------


class ApacAnalyzeNode(_RegionalBaseNode):
    """Regional analyze node for the APAC session (UTC 00:00-08:00)."""

    node_name: ClassVar[str] = "apac_analyze_node"
    tasks: ClassVar[list[NodeTask]] = [apac_analyze]
    _region_task: ClassVar[NodeTask] = apac_analyze


class EmeaAnalyzeNode(_RegionalBaseNode):
    """Regional analyze node for the EMEA session (UTC 08:00-16:00)."""

    node_name: ClassVar[str] = "emea_analyze_node"
    tasks: ClassVar[list[NodeTask]] = [emea_analyze]
    _region_task: ClassVar[NodeTask] = emea_analyze


class AmerAnalyzeNode(_RegionalBaseNode):
    """Regional analyze node for the AMER session (UTC 16:00-24:00)."""

    node_name: ClassVar[str] = "amer_analyze_node"
    tasks: ClassVar[list[NodeTask]] = [amer_analyze]
    _region_task: ClassVar[NodeTask] = amer_analyze


# Module-level callables registered with LangGraph StateGraph.
apac_analyze_node = ApacAnalyzeNode()
emea_analyze_node = EmeaAnalyzeNode()
amer_analyze_node = AmerAnalyzeNode()
