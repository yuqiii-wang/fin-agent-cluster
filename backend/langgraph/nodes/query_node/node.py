"""QueryNode — first node in the fin-analysis graph.

Hierarchy
---------
Thread
  └── query_node  (Workflow)
        ├── analyze_query                        (@task → Celery, sequential)
        ├── [get_stock_from_web_if_not_seen]     (@task → Celery, conditional WebRequest)
        ├── [analyze_stock_from_web_if_not_seen] (@task → Celery, conditional Streaming)
        ├── get_stock_region                     (@task → Celery, parallel)
        └── get_stock_industry_peers             (@task → Celery, parallel)

Flow
----
1. ``analyze_query`` asks the Ollama LLM to extract the stock name and flag
   whether the stock is recognised (``not_seen``).
2. When ``not_seen`` is True:
   a. ``get_stock_from_web_if_not_seen`` fetches a Wikipedia summary (WebRequest).
   b. ``analyze_stock_from_web_if_not_seen`` re-analyses using the web content
      (Streaming).  If still unrecognised it fails the node.
3. ``get_stock_region`` and ``get_stock_industry_peers`` run in parallel using
   the resolved stock name.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from backend.db.postgres.types import NodeType
from langchain_core.runnables import Runnable, RunnableLambda
from backend.langgraph.models.node import BaseNode
from backend.langgraph.models.models import NodeContext, TaskOutput
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.query_node.models import (
    QueryNodeInput, QueryNodeOutput, StockInfoInput, WebStockInput,
)
from backend.langgraph.nodes.query_node.tasks.analyze_query import analyze_query
from backend.langgraph.nodes.query_node.tasks.get_stock_from_web_if_not_seen import get_stock_from_web_if_not_seen
from backend.langgraph.nodes.query_node.tasks.analyze_stock_from_web_if_not_seen import (
    analyze_stock_from_web_if_not_seen,
    AnalyzeWebStockInput,
)
from backend.langgraph.nodes.query_node.tasks.get_stock_region import get_stock_region
from backend.langgraph.nodes.query_node.tasks.get_stock_industry_peers import get_stock_industry_peers
from backend.langgraph.state import GraphState


class QueryNode(BaseNode[QueryNodeInput, QueryNodeOutput]):
    """Sequential + conditional + parallel query node."""

    node_name = "query_node"
    node_type = NodeType.WORKFLOW
    tasks: ClassVar[list[NodeTask]] = [
        analyze_query,
        get_stock_from_web_if_not_seen,
        analyze_stock_from_web_if_not_seen,
        get_stock_region,
        get_stock_industry_peers,
    ]
    _prev_node_names: ClassVar[list[str]] = []

    async def build_input(self, state: GraphState) -> QueryNodeInput:
        """Read raw user query from GraphState.

        query is a thread-level primitive passed directly in the initial state.
        No DB read needed.
        """
        return QueryNodeInput(query=state.get("query", ""))

    def build_chain(self, ctx: NodeContext) -> Runnable[QueryNodeInput, dict[str, TaskOutput]]:
        """Chain: analyze_query → (optional web tasks) → parallel region + industry/peers."""
        async def _orchestrate(node_input: QueryNodeInput) -> dict[str, TaskOutput]:
            # Step 1: extract stock name
            analyze_result = await self.run_task(analyze_query, ctx, node_input)
            results: dict[str, TaskOutput] = {analyze_query.name: analyze_result}
            stock_name = analyze_result.content.stock_name

            # Step 2: web resolution when LLM did not recognise the stock
            if analyze_result.content.not_seen:
                web_input = WebStockInput(stock_name=stock_name, query=node_input.query)
                web_result = await self.run_task(get_stock_from_web_if_not_seen, ctx, web_input)
                results[get_stock_from_web_if_not_seen.name] = web_result

                analyze_web_input = AnalyzeWebStockInput(
                    stock_name=stock_name,
                    query=node_input.query,
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

            # Step 3: parallel region + industry/peers
            stock_input = StockInfoInput(stock_name=stock_name)
            region_result, industry_peers_result = await asyncio.gather(
                self.run_task(get_stock_region, ctx, stock_input),
                self.run_task(get_stock_industry_peers, ctx, stock_input),
            )
            results[get_stock_region.name] = region_result
            results[get_stock_industry_peers.name] = industry_peers_result
            return results

        return RunnableLambda(_orchestrate)

    def build_output(self, results: dict[str, TaskOutput]) -> QueryNodeOutput:
        """Compose final node output from task results."""
        # Prefer the confirmed stock name from the web streaming task if it ran.
        if analyze_stock_from_web_if_not_seen.name in results:
            stock_name = results[analyze_stock_from_web_if_not_seen.name].content.stock_name
        else:
            stock_name = results[analyze_query.name].content.stock_name

        region = results[get_stock_region.name].content.region
        industry = results[get_stock_industry_peers.name].content.industry
        peers = results[get_stock_industry_peers.name].content.peers
        return QueryNodeOutput(
            stock_name=stock_name,
            region=region,
            industry=industry,
            peers=peers,
        )

    def get_state_updates(self, output: QueryNodeOutput) -> dict[str, Any]:
        """Expose stock_name to GraphState for downstream routing."""
        return {"stock_name": output.stock_name}


# Module-level callable registered with LangGraph StateGraph.
query_node = QueryNode()
