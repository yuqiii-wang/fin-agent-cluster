"""stats_node — mock market-stats fetching LangGraph node.

Reads the ``query_response`` from state (produced by ``mock_query_node``) and
calls the :class:`~backend.resources.stats.client.StatsClient` to retrieve mock
market statistics. In production this would call a live market-data feed.

Node position in the pipeline:

    query_node → [news_node, stats_node] → merge_node ← fan-out / fan-in
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from langgraph.types import interrupt

from backend.graph.agents._shared.base_node import BaseNode
from backend.graph.agents.mock_perf.errors import STATS_FAILED
from backend.graph.state import StreamRunState
from backend.resources.stats import StatsClient

logger = logging.getLogger(__name__)


class MockStatsNode(BaseNode):
    """Mock stats node implementation."""

    node_name: str = "mock_stats"

    def _create_node_output(self, task_result) -> dict:
        return {
            "symbol": self._current_symbol,
            "period": self._current_period,
            "record_count": len(task_result),
        }

    def _log_completion(self, task_result, thread_id, node_id, elapsed_ms):
        logger.info(
            "[mock_stats] fetched %d records symbol=%s period=%s thread_id=%s node_id=%s elapsed_ms=%d",
            len(task_result), self._current_symbol, self._current_period, thread_id, node_id, elapsed_ms,
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
            "stats_records": task_result,
        }

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

        node_input = {
            "symbol": symbol,
            "period": period,
            "node_id": node_id,
            "task_id": task_id,
        }

        async def pre_execute_hook(thread_id_arg, node_id_arg):
            interrupt({"action": "step_approval", "node": self.node_name, "thread_id": thread_id_arg})

        async def task_runner(thread_id_arg, node_id_arg, node_execution_id_arg):
            from backend.sse_notifications import (
                TaskCancelledSignal,
                cancel_task,
                complete_task,
                create_task,
                fail_task,
            )

            await create_task(
                thread_id_arg,
                "MOCK_STATS",
                node_execution_id_arg,
                provider="mock",
                task_id=task_id,
                extra_payload={"node_id": node_id_arg, "symbol": symbol, "period": period},
            )

            try:
                client = StatsClient()
                response = await client.list_stats(symbol=symbol, period=period)
                records = [r.model_dump(mode="json") for r in response.items]
                if hasattr(client, "aclose"):
                    await client.aclose()
            except (asyncio.CancelledError, TaskCancelledSignal):
                await cancel_task(thread_id_arg, task_id, "MOCK_STATS")
                raise asyncio.CancelledError()
            except Exception as exc:
                logger.exception("[mock_stats] fetch error thread_id=%s: %s", thread_id_arg, exc)
                await fail_task(thread_id_arg, task_id, "MOCK_STATS", str(exc), error_code=STATS_FAILED)
                raise

            await complete_task(
                thread_id_arg,
                task_id,
                "MOCK_STATS",
                output={"symbol": symbol, "period": period, "record_count": len(records)},
            )
            return records

        return await self._execute_node_workflow(
            thread_id,
            parent_node_execution_id,
            node_input,
            task_runner,
            pre_execute_hook,
            use_start_finish=True,
        )


_mock_stats_instance = MockStatsNode()


async def mock_stats_node(state: StreamRunState) -> dict:
    """LangGraph node function wrapper for MockStatsNode class."""
    return await _mock_stats_instance(state)


__all__ = ["mock_stats_node"]
