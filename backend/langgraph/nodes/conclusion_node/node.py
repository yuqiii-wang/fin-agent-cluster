"""ConclusionNode — final node in the fin-analysis graph.

Hierarchy
---------
Thread
  └── conclusion_node  (Workflow)
        └── stream_conclusion  (@task → Celery stream worker)

Responsibilities
----------------
* Read research_subgraph output from ``fin_agents.node_executions`` via the
  PG replica (``read_node_output``).
* Run the ``stream_conclusion`` task to stream an LLM answer to the frontend.
* Write the final answer string to ``state["conclusion"]`` so executor.py
  can pass it to ``complete_thread``.

Agent upgrade path
------------------
Override ``orchestrate`` with an LLM agent that uses stream_conclusion as
a tool.  ``build_input`` and ``get_state_updates`` are unchanged.
"""

from __future__ import annotations

from typing import Any, ClassVar

from backend.db.postgres.types import NodeType
from langchain_core.runnables import Runnable, RunnableLambda
from backend.langgraph.lifecycle import read_node_output
from backend.langgraph.nodes.base.node import BaseNode
from backend.langgraph.nodes.base.models import NodeContext, TaskOutput
from backend.langgraph.nodes.base.task import NodeTask
from backend.langgraph.nodes.conclusion_node.models import ConclusionNodeInput, ConclusionNodeOutput
from backend.langgraph.nodes.conclusion_node.tasks.stream_conclusion import stream_conclusion
from backend.langgraph.state import GraphState


class ConclusionNode(BaseNode[ConclusionNodeInput, ConclusionNodeOutput]):
    """Fixed-flow conclusion node: single stream_conclusion task."""

    node_name = "conclusion_node"
    node_type = NodeType.WORKFLOW
    tasks: ClassVar[list[NodeTask]] = [stream_conclusion]
    _prev_node_names: ClassVar[list[str]] = ["analyze_stats_node", "analyze_news_node"]

    async def build_input(self, state: GraphState) -> ConclusionNodeInput:
        """Read analyze_stats_node and analyze_news_node outputs from the PG replica.

        Reads the outputs stored by both parallel analysis nodes in
        ``fin_agents.node_executions`` and builds the LLM prompt context.
        """
        stats_node_id = self._find_node_id_by_name(state, "analyze_stats_node")
        news_node_id = self._find_node_id_by_name(state, "analyze_news_node")

        stats_analysis: str = ""
        stats_key_metrics: dict = {}
        if stats_node_id:
            stats_output = await read_node_output(stats_node_id)
            stats_analysis = stats_output.get("stats_analysis", "")
            stats_key_metrics = stats_output.get("key_metrics", {})

        news_sentiment: str = ""
        news_highlights: list[str] = []
        if news_node_id:
            news_output = await read_node_output(news_node_id)
            news_sentiment = news_output.get("news_sentiment", "")
            news_highlights = news_output.get("highlights", [])

        return ConclusionNodeInput(
            stats_analysis=stats_analysis,
            stats_key_metrics=stats_key_metrics,
            news_sentiment=news_sentiment,
            news_highlights=news_highlights,
            query=state.get("query", ""),
        )

    def build_chain(self, ctx: NodeContext) -> Runnable[ConclusionNodeInput, dict[str, TaskOutput]]:
        """Chain step: stream_conclusion wrapped as a RunnableLambda."""
        return (
            self._task_as_runnable(stream_conclusion, ctx)
            | RunnableLambda(lambda r: {stream_conclusion.name: r})
        )

    def build_output(self, results: dict[str, TaskOutput]) -> ConclusionNodeOutput:
        """Node output is the stream_conclusion task's content directly."""
        return results[stream_conclusion.name].content

    def get_state_updates(self, output: ConclusionNodeOutput) -> dict[str, Any]:
        """Write final answer string to state["conclusion"]."""
        return {"conclusion": output.answer}


# Module-level callable registered with LangGraph StateGraph.
conclusion_node = ConclusionNode()
