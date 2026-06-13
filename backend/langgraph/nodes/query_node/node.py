"""QueryNode -- first node in the fin-analysis graph.

Hierarchy
---------
Thread
  └── query_node  (Workflow)
        ├── analyze_query                        (@task -> Celery, Streaming)
        ├── [get_stock_from_web_if_not_seen]     (@task -> Celery, conditional WebRequest)
        ├── [analyze_stock_from_web_if_not_seen] (@task -> Celery, conditional Streaming)
        └── get_and_calculate_stats              (TaskSeq -> get_stats + calculate_stats)

Flow
----
1. ``analyze_query`` asks the Ollama LLM to extract the stock name and flag
   whether the stock is recognised (``not_seen``).
2. When ``not_seen`` is True:
   a. ``get_stock_from_web_if_not_seen`` fetches a Wikipedia summary (WebRequest).
   b. ``analyze_stock_from_web_if_not_seen`` re-analyses using the web content
      (Streaming).  If still unrecognised it fails the node.
3. ``get_and_calculate_stats`` fetches 2 years of daily OHLCV bars for the
   confirmed stock, caches the raw record in ``input_raw``, computes technical
   indicators and upserts rows to ``quant_stats``, or bypasses recomputation
   when the cache is fresh.

Downstream
----------
``prepare_peers`` (Agent node) receives stock_name and uses the pre-populated
``quant_stats`` rows for peer validation.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, ClassVar

from backend.db.postgres.types import NodeType
from langchain_core.runnables import Runnable, RunnableLambda
from backend.langgraph.models.node import BaseNode
from backend.langgraph.models.models import NodeContext, TaskOutput
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.query_node.models import (
    QueryNodeInput, QueryNodeOutput, WebStockInput,
)
from backend.langgraph.nodes.query_node.tasks.analyze_query import analyze_query, AnalyzeQueryInput
from backend.langgraph.nodes.query_node.tasks.get_stock_from_web_if_not_seen import get_stock_from_web_if_not_seen
from backend.langgraph.nodes.query_node.tasks.analyze_stock_from_web_if_not_seen import (
    analyze_stock_from_web_if_not_seen,
    AnalyzeWebStockInput,
)
from backend.langgraph.state import GraphState


class QueryNode(BaseNode[QueryNodeInput, QueryNodeOutput]):
    """Sequential + conditional + parallel query node."""

    node_name = "query_node"
    node_type = NodeType.WORKFLOW
    display_name = "Query Node"
    category = "Query"
    config_fields: ClassVar[list[dict]] = [
        {
            "key": "human_in_the_loop",
            "label": "Review before routing",
            "type": "boolean",
            "description": "Pause after query parsing and wait for your approval before routing to analysis nodes.",
        },
    ]
    tasks: ClassVar[list[NodeTask]] = [
        analyze_query,
        get_stock_from_web_if_not_seen,
        analyze_stock_from_web_if_not_seen,
    ]
    _prev_node_names: ClassVar[list[str]] = []

    async def build_input(self, state: GraphState) -> QueryNodeInput:
        """Read raw user query from GraphState.

        query is a thread-level primitive passed directly in the initial state.
        No DB read needed.
        """
        return QueryNodeInput(query=state.get("query", ""))

    def build_chain(self, ctx: NodeContext) -> Runnable[QueryNodeInput, dict[str, TaskOutput]]:
        """Chain: analyze_query -> (optional web tasks)."""
        async def _orchestrate(node_input: QueryNodeInput) -> dict[str, TaskOutput]:
            query_stripped = node_input.query.strip()

            # Fast-path: single-token input is a direct symbol -- bypass LLM entirely.
            if len(query_stripped.split()) == 1:
                stock_name = query_stripped.upper()
                results: dict[str, Any] = {
                    analyze_query.name: SimpleNamespace(
                        content=SimpleNamespace(stock_name=stock_name)
                    )
                }
                return results  # type: ignore[return-value]

            # Step 1: extract stock name from query.
            analyze_result = await self.run_task(analyze_query, ctx, AnalyzeQueryInput(query=query_stripped))
            results = {analyze_query.name: analyze_result}

            stock_name = analyze_result.content.stock_name

            # Step 2: web resolution when LLM did not recognise the stock.
            if analyze_result.content.not_seen:
                web_input = WebStockInput(stock_name=stock_name, query=query_stripped)
                web_result = await self.run_task(get_stock_from_web_if_not_seen, ctx, web_input)
                results[get_stock_from_web_if_not_seen.name] = web_result

                analyze_web_input = AnalyzeWebStockInput(
                    stock_name=stock_name,
                    query=query_stripped,
                    web_title=web_result.content.title,
                    web_url=web_result.content.url,
                    web_content=web_result.content.content,
                )
                # Raises ValueError when the stock is still unrecognised after web analysis.
                analyze_web_result = await self.run_task(
                    analyze_stock_from_web_if_not_seen, ctx, analyze_web_input
                )
                results[analyze_stock_from_web_if_not_seen.name] = analyze_web_result
                stock_name = analyze_web_result.content.stock_name

            return results

        return RunnableLambda(_orchestrate)

    def build_output(self, results: dict[str, TaskOutput]) -> QueryNodeOutput:
        """Compose final node output from task results."""
        analyze_output = results[analyze_query.name].content
        return QueryNodeOutput(stock_name=analyze_output.stock_name)

    def get_state_updates(self, output: QueryNodeOutput) -> dict[str, Any]:
        """Expose stock_name to GraphState for downstream routing."""
        return {"stock_name": output.stock_name}


# Module-level callable registered with LangGraph StateGraph.
query_node = QueryNode()
