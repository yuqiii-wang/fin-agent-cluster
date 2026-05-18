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
from langchain_core.runnables import Runnable, RunnableLambda, RunnableParallel
from backend.langgraph.models.node import BaseNode
from backend.langgraph.models.models import NodeContext, TaskOutput
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.query_node.models import QueryNodeInput, QueryNodeOutput
from backend.langgraph.nodes.query_node.tasks.analyze_query import analyze_query
from backend.langgraph.nodes.query_node.tasks.capture_time import capture_time
from backend.langgraph.state import GraphState


class QueryNode(BaseNode[QueryNodeInput, QueryNodeOutput]):
    """Fixed-flow query node: analyze_query + capture_time run in parallel."""

    node_name = "query_node"
    node_type = NodeType.WORKFLOW
    tasks: ClassVar[list[NodeTask]] = [analyze_query, capture_time]
    _prev_node_names: ClassVar[list[str]] = []

    async def build_input(self, state: GraphState) -> QueryNodeInput:
        """Read raw user query from GraphState.

        query is a thread-level primitive passed directly in the initial state.
        No DB read needed.
        """
        return QueryNodeInput(query=state.get("query", ""))

    def build_chain(self, ctx: NodeContext) -> Runnable[QueryNodeInput, dict[str, TaskOutput]]:
        """Chain step: analyze_query and capture_time run in parallel."""
        return RunnableParallel(
            **{
                analyze_query.name: self._task_as_runnable(analyze_query, ctx),
                capture_time.name: self._task_as_runnable(capture_time, ctx),
            }
        )

    def build_output(self, results: dict[str, TaskOutput]) -> QueryNodeOutput:
        """Merge analyze_query result with the captured timestamp."""
        analysis = results[analyze_query.name].content
        time_result = results[capture_time.name].content
        return QueryNodeOutput(
            intent=analysis.intent,
            symbols=analysis.symbols,
            filters=analysis.filters,
            query_time=time_result.query_time,
        )

    def get_state_updates(self, output: QueryNodeOutput) -> dict[str, Any]:
        """Write query_time to state for the regional router.

        This is a plain scalar string (not a blob) so it does not inflate
        the LangGraph checkpoint.  All other query_node output is stored in
        node_executions via the lifecycle layer.
        """
        return {"query_time": output.query_time}


# Module-level callable registered with LangGraph StateGraph.
query_node = QueryNode()
