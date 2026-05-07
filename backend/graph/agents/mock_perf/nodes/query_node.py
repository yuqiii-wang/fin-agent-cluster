"""query_node — mock query-parser node that produces a structured JSON analysis request.

This node is the entry point for the mock analysis pipeline:

    query_node → [news_node, stats_node] → merge_node

It parses the incoming query string (or uses defaults) and hard-writes a mock
JSON response that subsequent nodes use to scope their data fetches. In a
production pipeline this would call an LLM to extract entities and parameters.

Trigger phrase: ``"DO STREAMING PERFORMANCE TEST NOW"`` (case-insensitive prefix).
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from langgraph.types import interrupt

from backend.graph.state import StreamRunState
from backend.graph.agents._shared.base_node import BaseNode
from backend.graph.agents.mock_perf.errors import QUERY_FAILED

logger = logging.getLogger(__name__)

# ── Mock JSON response template ────────────────────────────────────────────
# Hard-coded to demonstrate the query-parsing stage without real LLM calls.
_MOCK_QUERY_RESPONSE: dict = {
    "symbol": "AAPL",
    "analysis_type": "comprehensive",
    "time_horizon": "1w",
    "parameters": {
        "limit_news": 5,
        "period": "1d",
        "indicators": ["close", "volume", "sma_20", "rsi_14"],
    },
    "rationale": (
        "Mock analysis request for AAPL covering 1-week horizon with "
        "intraday stats and latest 5 news articles."
    ),
}


class MockQueryNode(BaseNode):
    """Mock query node implementation."""

    node_name: str = "mock_query"

    def _create_node_output(self, task_result) -> dict:
        return {"query_response": task_result}

    def _log_completion(self, task_result, thread_id, node_id, elapsed_ms):
        logger.info(
            "[mock_query] completed symbol=%s thread_id=%s node_id=%s elapsed_ms=%d",
            task_result.get("symbol"), thread_id, node_id, elapsed_ms,
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
            "task_id": task_id,
            "query_response": task_result,
        }

    async def __call__(self, state: StreamRunState) -> dict:
        thread_id: str = state["thread_id"]
        parent_node_execution_id: int | None = state.get("node_execution_id")
        query: str = state.get("query", "")

        node_id: str = str(uuid.uuid4())
        task_id: str = str(uuid.uuid4())

        node_input = {
            "query": query,
            "node_id": node_id,
            "task_id": task_id,
        }

        async def pre_execute_hook(thread_id_arg, node_id_arg):
            interrupt({"action": "step_approval", "node": self.node_name, "thread_id": thread_id_arg})

        async def task_runner(thread_id_arg, node_id_arg, node_execution_id_arg):
            # Import here to avoid circular import
            from backend.sse_notifications import (
                TaskCancelledSignal,
                cancel_task,
                complete_task,
                create_task,
                fail_task,
            )

            await create_task(
                thread_id_arg,
                "QUERY",
                node_execution_id_arg,
                provider="mock",
                task_id=task_id,
                extra_payload={"node_id": node_id_arg},
            )

            try:
                response = dict(_MOCK_QUERY_RESPONSE)
            except (asyncio.CancelledError, TaskCancelledSignal):
                await cancel_task(thread_id_arg, task_id, "QUERY")
                raise asyncio.CancelledError()
            except Exception as exc:
                logger.exception("[mock_query] parse error thread_id=%s: %s", thread_id_arg, exc)
                await fail_task(thread_id_arg, task_id, "QUERY", str(exc), error_code=QUERY_FAILED)
                raise

            await complete_task(
                thread_id_arg,
                task_id,
                "QUERY",
                output={"query_response": response},
            )
            return response

        return await self._execute_node_workflow(
            thread_id,
            parent_node_execution_id,
            node_input,
            task_runner,
            pre_execute_hook,
            use_start_finish=True,
        )


_mock_query_instance = MockQueryNode()


async def mock_query_node(state: StreamRunState) -> dict:
    """LangGraph node function wrapper for MockQueryNode class."""
    return await _mock_query_instance(state)


__all__ = ["mock_query_node"]
