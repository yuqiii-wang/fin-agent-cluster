"""AnalyzeNewsNode — analyses news sentiment from research_subgraph.

Hierarchy
---------
Thread
  └── analyze_news_node  (Workflow)
        └── analyze_news  (@task → Celery completion worker)

Responsibilities
----------------
* Read research_subgraph output from ``fin_agents.node_executions`` via the
  PG replica (``read_node_output``).
* Extract ``news_data`` and run the ``analyze_news`` task.
* Produce ``AnalyzeNewsOutput`` stored in node_executions for conclusion_node.

Agent upgrade path
------------------
Override ``orchestrate`` with an LLM agent that uses analyze_news as a tool.
"""

from __future__ import annotations

from typing import Any, ClassVar

from backend.db.postgres.types import NodeType
from langchain_core.runnables import Runnable, RunnableLambda
from backend.langgraph.lifecycle import read_node_output
from backend.langgraph.nodes.base.node import BaseNode
from backend.langgraph.nodes.base.models import NodeContext, TaskOutput
from backend.langgraph.nodes.base.task import NodeTask
from backend.langgraph.nodes.analyze_news_node.models import AnalyzeNewsInput, AnalyzeNewsOutput
from backend.langgraph.nodes.analyze_news_node.tasks.analyze_news import analyze_news
from backend.langgraph.state import GraphState


class AnalyzeNewsNode(BaseNode[AnalyzeNewsInput, AnalyzeNewsOutput]):
    """Fixed-flow analyze_news node: single analyze_news task."""

    node_name = "analyze_news_node"
    node_type = NodeType.WORKFLOW
    tasks: ClassVar[list[NodeTask]] = [analyze_news]
    _prev_node_names: ClassVar[list[str]] = ["research_subgraph"]
    parallel_group: ClassVar[str | None] = "analysis"

    async def build_input(self, state: GraphState) -> AnalyzeNewsInput:
        """Read research_subgraph output from the PG replica.

        Extracts ``news_data`` for sentiment analysis.
        """
        subgraph_id = self._find_node_id_by_name(state, "research_subgraph")
        news_data: dict = {}
        if subgraph_id:
            output = await read_node_output(subgraph_id)
            news_data = output.get("news_data", {})
        return AnalyzeNewsInput(
            news_data=news_data,
            query=state.get("query", ""),
        )

    def build_chain(self, ctx: NodeContext) -> Runnable[AnalyzeNewsInput, dict[str, TaskOutput]]:
        """Chain step: analyze_news wrapped as a RunnableLambda."""
        return (
            self._task_as_runnable(analyze_news, ctx)
            | RunnableLambda(lambda r: {analyze_news.name: r})
        )

    def build_output(self, results: dict[str, TaskOutput]) -> AnalyzeNewsOutput:
        """Node output is the analyze_news task's content directly."""
        return results[analyze_news.name].content

    def get_state_updates(self, output: AnalyzeNewsOutput) -> dict[str, Any]:
        """No state updates — output stored in node_executions via lifecycle."""
        return {}


# Module-level callable registered with LangGraph StateGraph.
analyze_news_node = AnalyzeNewsNode()
