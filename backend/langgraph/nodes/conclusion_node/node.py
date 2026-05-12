"""ConclusionNode — final node in the fin-analysis graph.

Hierarchy
---------
Thread
  └── conclusion_node  (Workflow)
        └── stream_conclusion  (@task → Celery stream worker)

Responsibilities
----------------
* Read merged research summary and original user query from GraphState.
* Run the ``stream_conclusion`` task to stream an LLM answer to the frontend.
* Write the final answer string to ``state["conclusion"]``.

Agent upgrade path
------------------
Override ``orchestrate`` with an LLM agent that uses stream_conclusion as
a tool.  ``build_input`` and ``get_state_updates`` are unchanged.
"""

from __future__ import annotations

from typing import Any

from backend.db.postgres.types import NodeType
from langchain_core.runnables import Runnable, RunnableLambda
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
    tasks: list[NodeTask] = [stream_conclusion]

    def build_input(self, state: GraphState) -> ConclusionNodeInput:
        """Read merged_research and original query from GraphState."""
        return ConclusionNodeInput(
            merged_research=state.get("merged_research", {}),
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
