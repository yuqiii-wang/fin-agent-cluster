"""node — thin LangGraph node function for the stats fetch stage.

Node position in the pipeline::

    query_node → [news_node, stats_node] → merge_node  ← fan-out / fan-in

NOTE: ``interrupt()`` is intentionally NOT used here.  See news_node/node.py
for the full rationale — parallel fan-out nodes sharing the same interrupt()
checkpoint cause sequential ``Command(resume=True)`` passes to re-execute
already-completed @tasks (different node_execution_ids per pass).
"""

from __future__ import annotations

import logging
import uuid

from backend.graph.agents._shared.base_node import BaseNode
from backend.graph.agents._shared.nodes.stats_node.models import StatsNodeInput, StatsNodeOutput
from backend.graph.agents._shared.nodes.stats_node.tasks import run_fetch_stats_task
from backend.graph.state import StreamRunState

logger = logging.getLogger(__name__)


class StatsNode(BaseNode):
    """Stats node implementation."""

    node_name: str = "mock_stats"

    def _create_node_output(self, task_result):
        return StatsNodeOutput(
            symbol=self._current_symbol, 
            period=self._current_period, 
            record_count=len(task_result)
        )

    def _log_completion(self, task_result, thread_id, node_id, elapsed_ms):
        logger.info(
            "[mock_stats] fetched %d records symbol=%s period=%s thread_id=%s node_id=%s elapsed_ms=%d",
            len(task_result), self._current_symbol, self._current_period, thread_id, node_id, elapsed_ms,
        )

    def _create_state_update(self, node_execution_id, node_id, task_id, task_result):
        return {"stats_node_execution_id": node_execution_id, "stats_records": task_result}

    async def __call__(self, state: StreamRunState) -> dict:
        thread_id: str = state["thread_id"]
        parent_node_execution_id: int | None = state.get("node_execution_id")
        query_response: dict = state.get("query_response") or {}
        symbol: str = query_response.get("symbol", "AAPL")
        period: str = query_response.get("parameters", {}).get("period", "1d")

        self._current_symbol = symbol
        self._current_period = period
        node_id: str = str(uuid.uuid4())
        task_id: str = str(uuid.uuid4())

        node_input = StatsNodeInput(symbol=symbol, period=period, node_id=node_id, task_id=task_id)

        async def task_runner(thread_id_arg, node_id_arg, node_execution_id_arg):
            return await run_fetch_stats_task(
                thread_id_arg, task_id, node_execution_id_arg, node_id_arg,
                symbol=symbol, period=period,
            )

        return await self._execute_node_workflow(
            thread_id,
            [parent_node_execution_id] if parent_node_execution_id else [],
            node_input,
            task_runner,
        )


_stats_node_instance = StatsNode()


async def mock_stats_node(state: StreamRunState) -> dict:
    """LangGraph node function wrapper for StatsNode class."""
    return await _stats_node_instance(state)


__all__ = ["mock_stats_node"]

