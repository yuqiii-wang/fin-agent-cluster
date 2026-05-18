"""AnalyzeStatsNode — analyses OHLCV statistics from research_subgraph.

Hierarchy
---------
Thread
  └── analyze_stats_node  (Workflow)
        └── analyze_stats  (@task → Celery completion worker)

Responsibilities
----------------
* Read research_subgraph output from ``fin_agents.node_executions`` via the
  PG replica (``read_node_output``).
* Extract ``stats_data`` and run the ``analyze_stats`` task.
* Produce ``AnalyzeStatsOutput`` stored in node_executions for conclusion_node.

Agent upgrade path
------------------
Override ``orchestrate`` with an LLM agent that uses analyze_stats as a tool.
"""

from __future__ import annotations

from typing import Any, ClassVar

from backend.db.postgres.types import NodeType
from langchain_core.runnables import Runnable, RunnableLambda
from backend.langgraph.lifecycle import read_node_output
from backend.langgraph.models.node import BaseNode
from backend.langgraph.models.models import NodeContext, TaskOutput
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.mock_analyze_stats_node.models import AnalyzeStatsInput, AnalyzeStatsOutput
from backend.langgraph.nodes.mock_analyze_stats_node.tasks.analyze_stats import analyze_stats
from backend.langgraph.state import GraphState


class AnalyzeStatsNode(BaseNode[AnalyzeStatsInput, AnalyzeStatsOutput]):
    """Fixed-flow analyze_stats node: single analyze_stats task."""

    node_name = "analyze_stats_node"
    node_type = NodeType.WORKFLOW
    view_type = "Mirror"
    tasks: ClassVar[list[NodeTask]] = [analyze_stats]
    _prev_node_names: ClassVar[list[str]] = ["research_subgraph"]
    parallel_group: ClassVar[str | None] = "analysis"

    async def build_input(self, state: GraphState) -> AnalyzeStatsInput:
        """Read research_subgraph output from the PG replica.

        Extracts ``stats_data`` for statistical analysis.
        """
        subgraph_id = self._find_node_id_by_name(state, "research_subgraph")
        stats_data: dict = {}
        if subgraph_id:
            output = await read_node_output(subgraph_id)
            stats_data = output.get("stats_data", {})
        return AnalyzeStatsInput(
            stats_data=stats_data,
            query=state.get("query", ""),
        )

    def build_chain(self, ctx: NodeContext) -> Runnable[AnalyzeStatsInput, dict[str, TaskOutput]]:
        """Chain step: analyze_stats wrapped as a RunnableLambda."""
        return (
            self._task_as_runnable(analyze_stats, ctx)
            | RunnableLambda(lambda r: {analyze_stats.name: r})
        )

    def build_output(self, results: dict[str, TaskOutput]) -> AnalyzeStatsOutput:
        """Node output is the analyze_stats task's content directly."""
        return results[analyze_stats.name].content

    def get_state_updates(self, output: AnalyzeStatsOutput) -> dict[str, Any]:
        """No state updates — output stored in node_executions via lifecycle."""
        return {}


# Module-level callable registered with LangGraph StateGraph.
analyze_stats_node = AnalyzeStatsNode()
