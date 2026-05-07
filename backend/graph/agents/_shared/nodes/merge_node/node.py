"""node — thin LangGraph node function for the merge (fan-in) stage.

Node position in the pipeline::

    query_node → [news_node, stats_node] → merge_node → analysis_node → END

Fan-in edge topology: receives ``parent_node_execution_ids`` from both
``news_node`` and ``stats_node`` so the graph visualisation shows two
inbound edges.
"""

from __future__ import annotations

import logging
import uuid

from langgraph.types import interrupt

from backend.graph.agents._shared.base_node import BaseNode
from backend.graph.agents._shared.nodes.merge_node.models import (
    MergeNodeInput,
    MergeNodeOutput,
)
from backend.graph.agents._shared.nodes.merge_node.tasks.merge import run_merge_task
from backend.graph.state import StreamRunState

logger = logging.getLogger(__name__)


class MergeNode(BaseNode):
    """Merge node implementation."""

    node_name: str = "merge"

    def _create_node_output(self, task_result):
        merged_dict = task_result.as_dict()
        return MergeNodeOutput(
            symbol=self._current_symbol,
            news_count=self._current_news_count,
            stats_count=self._current_stats_count,
            merged_keys=list(merged_dict.keys()),
        )

    def _log_completion(self, task_result, thread_id, node_id, elapsed_ms):
        logger.info(
            "[merge] merged symbol=%s articles=%d records=%d thread_id=%s node_id=%s elapsed_ms=%d",
            self._current_symbol, self._current_news_count, self._current_stats_count,
            thread_id, node_id, elapsed_ms,
        )

    def _create_state_update(self, node_execution_id, node_id, task_id, task_result):
        return {
            "node_execution_id": node_execution_id,
            "node_id": node_id,
            "task_id": task_id,
            "merged_analysis": task_result.as_dict(),
        }

    async def __call__(self, state: StreamRunState) -> dict:
        thread_id: str = state["thread_id"]
        news_exec_id: int | None = state.get("news_node_execution_id")
        stats_exec_id: int | None = state.get("stats_node_execution_id")
        news_articles: list[dict] = state.get("news_articles") or []
        stats_records: list[dict] = state.get("stats_records") or []
        query_response: dict = state.get("query_response") or {}

        parent_ids: list[int] = [x for x in [news_exec_id, stats_exec_id] if x is not None]
        symbol: str = query_response.get("symbol", "AAPL")
        analysis_type: str = query_response.get("analysis_type", "comprehensive")
        time_horizon: str = query_response.get("time_horizon", "1w")

        self._current_symbol = symbol
        self._current_news_count = len(news_articles)
        self._current_stats_count = len(stats_records)

        node_id: str = str(uuid.uuid4())
        task_id: str = str(uuid.uuid4())

        logger.info(
            "[merge] symbol=%s articles=%d stat_records=%d parent_ids=%s thread_id=%s",
            symbol, len(news_articles), len(stats_records), parent_ids, thread_id,
        )

        node_input = MergeNodeInput(
            article_count=len(news_articles),
            stat_record_count=len(stats_records),
            node_id=node_id,
            task_id=task_id,
        )

        async def pre_execute_hook(thread_id_arg, node_id_arg):
            interrupt({"action": "step_approval", "node": self.node_name, "thread_id": thread_id_arg})

        async def task_runner(thread_id_arg, node_id_arg, node_execution_id_arg):
            meta: dict = {
                "symbol": symbol,
                "analysis_type": analysis_type,
                "time_horizon": time_horizon,
            }
            return await run_merge_task(
                thread_id_arg, task_id, node_execution_id_arg, node_id_arg,
                news_json=news_articles,
                stats_json=stats_records,
                meta=meta,
            )

        return await self._execute_node_workflow(
            thread_id,
            parent_ids,
            node_input,
            task_runner,
            pre_execute_hook,
        )


_merge_node_instance = MergeNode()


async def merge_node(state: StreamRunState) -> dict:
    """LangGraph node function wrapper for MergeNode class."""
    return await _merge_node_instance(state)


__all__ = ["merge_node"]
