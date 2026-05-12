"""QueryNode — first node in the fin-analysis graph.

Hierarchy
---------
Thread
  └── query_node  (Workflow)
        └── analyze_query  (@task → Celery completion worker)

Responsibilities
----------------
* Read raw user query from GraphState.
* Run the ``analyze_query`` task to extract intent and equity symbols.
* Write the typed result to ``state["query_analysis"]`` for the
  research_subgraph to consume.

Agent upgrade path
------------------
Override ``orchestrate`` with an LLM ReAct loop that calls
``self.run_task(analyze_query, ctx, node_input)`` as a tool.  All other
methods — ``build_input``, ``build_output``, ``get_state_updates`` — are
unchanged because the inter-node data contract stays the same.
"""

from __future__ import annotations

from typing import Any

from backend.db.postgres.types import NodeType
from langchain_core.runnables import Runnable, RunnableLambda
from backend.langgraph.nodes.base.node import BaseNode
from backend.langgraph.nodes.base.models import NodeContext, TaskOutput
from backend.langgraph.nodes.base.task import NodeTask
from backend.langgraph.nodes.query_node.models import QueryNodeInput, QueryNodeOutput
from backend.langgraph.nodes.query_node.tasks.analyze_query import analyze_query
from backend.langgraph.state import GraphState


class QueryNode(BaseNode[QueryNodeInput, QueryNodeOutput]):
    """Fixed-flow query node: single analyze_query task."""

    node_name = "query_node"
    node_type = NodeType.WORKFLOW
    tasks: list[NodeTask] = [analyze_query]

    def build_input(self, state: GraphState) -> QueryNodeInput:
        """Read raw user query from GraphState."""
        return QueryNodeInput(query=state.get("query", ""))

    def build_chain(self, ctx: NodeContext) -> Runnable[QueryNodeInput, dict[str, TaskOutput]]:
        """Chain step: analyze_query wrapped as a RunnableLambda."""
        return (
            self._task_as_runnable(analyze_query, ctx)
            | RunnableLambda(lambda r: {analyze_query.name: r})
        )

    def build_output(self, results: dict[str, TaskOutput]) -> QueryNodeOutput:
        """Node output is the analyze_query task's content directly."""
        return results[analyze_query.name].content

    def get_state_updates(self, output: QueryNodeOutput) -> dict[str, Any]:
        """Write to state["query_analysis"] for the research_subgraph."""
        return {"query_analysis": output.model_dump()}


# Module-level callable registered with LangGraph StateGraph.
query_node = QueryNode()
