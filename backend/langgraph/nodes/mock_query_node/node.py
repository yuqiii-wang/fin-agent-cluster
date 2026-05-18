"""QueryNode — first node in the fin-analysis graph.

Hierarchy
---------
Thread
  └── query_node  (Workflow)
        └── analyze_query  (@task → Celery completion worker)

Responsibilities
----------------
* Read raw user query from GraphState (query is a thread-level primitive,
  not a node output, so no DB read is needed).
* Run the ``analyze_query`` task to extract intent and equity symbols.
* Write execution output to ``fin_agents.node_executions`` via lifecycle.
  Downstream nodes read this output via ``read_node_output(node_id)``.

Agent upgrade path
------------------
Override ``orchestrate`` with an LLM ReAct loop that calls
``self.run_task(analyze_query, ctx, node_input)`` as a tool.  All other
methods — ``build_input``, ``build_output``, ``get_state_updates`` — are
unchanged because the inter-node data contract stays the same.
"""

from __future__ import annotations

from typing import Any, ClassVar

from backend.db.postgres.types import NodeType
from langchain_core.runnables import Runnable, RunnableLambda
from backend.langgraph.models.node import BaseNode
from backend.langgraph.models.models import NodeContext, TaskOutput
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.mock_query_node.models import QueryNodeInput, QueryNodeOutput
from backend.langgraph.nodes.mock_query_node.tasks.analyze_query import analyze_query
from backend.langgraph.state import GraphState


class QueryNode(BaseNode[QueryNodeInput, QueryNodeOutput]):
    """Fixed-flow query node: analyze_query runs as a single task."""

    node_name = "query_node"
    node_type = NodeType.WORKFLOW
    tasks: ClassVar[list[NodeTask]] = [analyze_query]
    _prev_node_names: ClassVar[list[str]] = []

    async def build_input(self, state: GraphState) -> QueryNodeInput:
        """Read raw user query from GraphState.

        query is a thread-level primitive passed directly in the initial state.
        No DB read needed.
        """
        return QueryNodeInput(query=state.get("query", ""))

    def build_chain(self, ctx: NodeContext) -> Runnable[QueryNodeInput, dict[str, TaskOutput]]:
        """Chain step: run analyze_query as a single task."""
        return (
            self._task_as_runnable(analyze_query, ctx)
            | RunnableLambda(lambda r: {analyze_query.name: r})
        )

    def build_output(self, results: dict[str, TaskOutput]) -> QueryNodeOutput:
        """Build output from analyze_query result."""
        analysis = results[analyze_query.name].content
        return QueryNodeOutput(
            intent=analysis.intent,
            symbols=analysis.symbols,
            filters=analysis.filters,
        )

    def get_state_updates(self, output: QueryNodeOutput) -> dict[str, Any]:
        """No state updates — all output is stored via the lifecycle layer."""
        return {}


# Module-level callable registered with LangGraph StateGraph.
query_node = QueryNode()
