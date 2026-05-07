"""merge_node — fan-in node that merges news + stats and runs the stream ingest/digest.

Node position in the pipeline:

    query_node → [news_node, stats_node] → merge_node → END
"""

from __future__ import annotations

import logging
import uuid

from langgraph.types import interrupt

from backend.graph.agents._shared.base_node import BaseNode
from backend.graph.state import StreamRunState

logger = logging.getLogger(__name__)

_BASE_TOKENS: int = 5_000
_TOKENS_PER_ARTICLE: int = 200
_TOKENS_PER_STAT: int = 100
_MAX_TOKENS: int = 20_000
_INGEST_TIMEOUT_SECS: int = 30


def _compute_token_budget(news_articles: list[dict], stats_records: list[dict]) -> int:
    """Compute a token budget that scales with the volume of merged data."""
    budget = (
        _BASE_TOKENS
        + len(news_articles) * _TOKENS_PER_ARTICLE
        + len(stats_records) * _TOKENS_PER_STAT
    )
    return min(budget, _MAX_TOKENS)


class MockMergeNode(BaseNode):
    """Mock merge node implementation."""

    node_name: str = "merge"

    def _create_node_output(self, task_result) -> dict:
        # run_throughput_task handles finish_node_execution internally,
        # so we just need to return dummy dict for BaseNode
        return {}

    def _log_completion(self, task_result, thread_id, node_id, elapsed_ms):
        logger.info(
            "[merge] merged symbol=%s articles=%d records=%d thread_id=%s node_id=%s elapsed_ms=%d",
            self._current_symbol, self._current_news_count, self._current_stats_count,
            thread_id, node_id, elapsed_ms,
        )

    def _create_state_update(
        self,
        node_execution_id,
        node_id,
        task_id,
        task_result,
    ) -> dict:
        return {
            "node_execution_id": node_execution_id,
            "node_id": node_id,
            "task_id": task_result.pub_task_id,
            "stream_id": self._stream_id,
            "result": task_result.result_str,
        }

    async def __call__(self, state: StreamRunState) -> dict:
        from backend.graph.agents.mock_perf.tasks.throughput import run_throughput_task

        thread_id: str = state["thread_id"]
        parent_node_execution_id: int | None = state.get("node_execution_id")
        news_articles: list[dict] = state.get("news_articles") or []
        stats_records: list[dict] = state.get("stats_records") or []
        query_response: dict = state.get("query_response") or {}
        symbol: str = (query_response or {}).get("symbol", "?")

        self._current_symbol = symbol
        self._current_news_count = len(news_articles)
        self._current_stats_count = len(stats_records)

        total_tokens = _compute_token_budget(news_articles, stats_records)

        logger.info(
            "[merge] symbol=%s articles=%d stat_records=%d tokens=%d thread_id=%s",
            symbol, len(news_articles), len(stats_records), total_tokens, thread_id,
        )

        node_id: str = str(uuid.uuid4())
        task_id: str = str(uuid.uuid4())
        self._stream_id: str = str(uuid.uuid4())

        node_input = {
            "article_count": len(news_articles),
            "stat_record_count": len(stats_records),
            "total_tokens": total_tokens,
            "node_id": node_id,
            "task_id": task_id,
            "stream_id": self._stream_id,
        }

        async def pre_execute_hook(thread_id_arg, node_id_arg):
            interrupt({"action": "step_approval", "node": self.node_name, "thread_id": thread_id_arg})

        async def task_runner(thread_id_arg, node_id_arg, node_execution_id_arg):
            return await run_throughput_task(
                thread_id=thread_id_arg,
                total_tokens=total_tokens,
                timeout_secs=_INGEST_TIMEOUT_SECS,
                node_execution_id=node_execution_id_arg,
                node_id=node_id_arg,
                task_id=task_id,
                stream_id=self._stream_id,
                task_name_override="MERGE",
                t0_node=None,
            )

        return await self._execute_node_workflow(
            thread_id,
            parent_node_execution_id,
            node_input,
            task_runner,
            pre_execute_hook,
            use_start_finish=True,
        )


_mock_merge_instance = MockMergeNode()


async def merge_node(state: StreamRunState) -> dict:
    """LangGraph node function wrapper for MockMergeNode class."""
    return await _mock_merge_instance(state)


__all__ = ["merge_node"]
