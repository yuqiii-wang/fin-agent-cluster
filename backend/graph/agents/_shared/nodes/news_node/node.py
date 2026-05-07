"""node — thin LangGraph node function for the news fetch stage.

Node position in the pipeline::

    query_node → [news_node, stats_node] → merge_node  ← fan-out / fan-in

NOTE: ``interrupt()`` is intentionally NOT used here.  In a parallel fan-out
(news_node + stats_node both scheduled concurrently), simultaneous interrupt()
calls share the same LangGraph checkpoint.  Each successive ``Command(resume=True)``
loads the original shared checkpoint where neither @task has run yet, causing
each fan-out node to re-execute on every subsequent resume pass (duplicate
node_execution_ids in the UI).  Removing interrupt() from these fast fan-out
nodes lets the StateGraph's standard node-completion checkpointing handle
deduplication correctly.
"""

from __future__ import annotations

import logging
import uuid

from backend.graph.agents._shared.base_node import BaseNode
from backend.graph.agents._shared.nodes.news_node.models import NewsNodeInput, NewsNodeOutput
from backend.graph.agents._shared.nodes.news_node.tasks import run_fetch_news_task
from backend.graph.state import StreamRunState

logger = logging.getLogger(__name__)


class NewsNode(BaseNode):
    """News node implementation."""

    node_name: str = "mock_news"

    def _create_node_output(self, task_result):
        return NewsNodeOutput(symbol=self._current_symbol, article_count=len(task_result))

    def _log_completion(self, task_result, thread_id, node_id, elapsed_ms):
        logger.info(
            "[mock_news] fetched %d articles symbol=%s thread_id=%s node_id=%s elapsed_ms=%d",
            len(task_result), self._current_symbol, thread_id, node_id, elapsed_ms,
        )

    def _create_state_update(self, node_execution_id, node_id, task_id, task_result):
        return {"news_node_execution_id": node_execution_id, "news_articles": task_result}

    async def __call__(self, state: StreamRunState) -> dict:
        thread_id: str = state["thread_id"]
        parent_node_execution_id: int | None = state.get("node_execution_id")
        query_response: dict = state.get("query_response") or {}
        symbol: str = query_response.get("symbol", "AAPL")
        limit: int = int(query_response.get("parameters", {}).get("limit_news", 5))

        self._current_symbol = symbol
        node_id: str = str(uuid.uuid4())
        task_id: str = str(uuid.uuid4())

        node_input = NewsNodeInput(symbol=symbol, limit=limit, node_id=node_id, task_id=task_id)

        async def task_runner(thread_id_arg, node_id_arg, node_execution_id_arg):
            return await run_fetch_news_task(
                thread_id_arg, task_id, node_execution_id_arg, node_id_arg,
                symbol=symbol, limit=limit,
            )

        return await self._execute_node_workflow(
            thread_id,
            [parent_node_execution_id] if parent_node_execution_id else [],
            node_input,
            task_runner,
        )


_news_node_instance = NewsNode()


async def mock_news_node(state: StreamRunState) -> dict:
    """LangGraph node function wrapper for NewsNode class."""
    return await _news_node_instance(state)


__all__ = ["mock_news_node"]

