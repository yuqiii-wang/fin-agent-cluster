"""node — LangGraph node function for the mock_single report stage.

Receives the analysis result from ``mock_analysis_node`` and runs the
opt-in streaming report task.  By default, tokens are buffered in Redis
and not streamed to the UI.  The user can enable live streaming by clicking
the task in the graph inspector (``POST .../tasks/{task_id}/enable-stream``).

Node position in the pipeline::

    (outer graph) mock_analysis → mock_report → END

Design note — no ``interrupt()``
---------------------------------
Pause is handled by direct ``asyncio.Task.cancel()``, same as the analysis
node.  ``CancelledError`` propagates naturally through the async call stack.
"""

from __future__ import annotations

import logging
import uuid

from backend.graph.state import StreamRunState
from backend.graph.agents._shared.base_node import BaseNode
from backend.graph.agents.mock_single.nodes.report_node.tasks import run_mock_report_task

logger = logging.getLogger(__name__)

_TOKEN_PER_SEC: int = 30    # generation rate (tokens/s)
_TIMEOUT_SECS: int = 10     # hard deadline


class MockReportNode(BaseNode):
    """Mock report node — opt-in streaming token generation for trading signal report."""

    node_name: str = "mock_report"

    def _create_node_output(self, task_result) -> dict:
        return {"result": task_result.result_str}

    def _log_completion(self, task_result, thread_id, node_id, elapsed_ms):
        logger.info(
            "[mock_report] completed thread_id=%s node_id=%s elapsed_ms=%d produced=%d recommendation=%s",
            thread_id, node_id, elapsed_ms, task_result.produced, task_result.recommendation,
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
            "result": task_result.result_str,
        }

    async def __call__(self, state: StreamRunState) -> dict:
        thread_id: str = state["thread_id"]
        parent_node_execution_id: int | None = state.get("node_execution_id")
        symbol: str = (state.get("merged_analysis") or {}).get("symbol", "AAPL")

        logger.info(
            "[mock_report] symbol=%s token_per_sec=%d timeout_secs=%d thread_id=%s",
            symbol, _TOKEN_PER_SEC, _TIMEOUT_SECS, thread_id,
        )

        node_id: str = str(uuid.uuid4())
        task_id: str = str(uuid.uuid4())

        node_input = {
            "node_id": node_id,
            "task_id": task_id,
            "token_per_sec": _TOKEN_PER_SEC,
            "timeout_secs": _TIMEOUT_SECS,
        }

        async def task_runner(thread_id_arg: str, node_id_arg: str, node_execution_id_arg: int):
            return await run_mock_report_task(
                thread_id=thread_id_arg,
                task_id=task_id,
                node_execution_id=node_execution_id_arg,
                t0_node=None,
            )

        return await self._execute_node_workflow(
            thread_id,
            parent_node_execution_id,
            node_input,
            task_runner,
            use_start_finish=False,
        )


_mock_report_instance = MockReportNode()


async def mock_report_node(state: StreamRunState) -> dict:
    """LangGraph node function wrapper for MockReportNode class."""
    return await _mock_report_instance(state)


__all__ = ["mock_report_node"]
