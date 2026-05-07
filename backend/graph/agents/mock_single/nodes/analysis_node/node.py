"""node — LangGraph node function for the mock_single analysis stage.

Receives the ``merged_analysis`` JSON payload from ``merge_node`` and runs
the opt-in streaming analysis task.  By default, tokens are buffered in Redis
and not streamed to the UI.  The user can enable live streaming by clicking
the task in the graph inspector (``POST .../tasks/{task_id}/enable-stream``).

Node position in the pipeline::

    (outer graph) mock_single_subgraph → mock_analysis → END

The ``mock_analysis`` node is wired DIRECTLY to the outer routing graph (not
inside the nested ``mock_single_subgraph``).

Design note — no ``interrupt()``
---------------------------------
An earlier design called ``interrupt()`` here so that a pause signal could be
honored at this checkpoint boundary. That design was abandoned because:

1. ``interrupt()`` inside an outer-graph StateGraph node causes
   ``Command(resume=True)`` to load an earlier checkpoint (before
   ``mock_single_subgraph`` ran), re-triggering the router and looping.
2. Pause is now handled by direct ``asyncio.Task.cancel()`` in
   ``pause_query`` (same as cancel), so no checkpoint boundary is needed.

``CancelledError`` from a direct cancel propagates naturally through
``_run_analysis_node`` → ``mock_analysis_node`` → the asyncio task wrapper.
"""

from __future__ import annotations

import logging
import uuid

from backend.graph.state import StreamRunState
from backend.graph.agents._shared.base_node import BaseNode
from backend.graph.agents.mock_single.nodes.analysis_node.tasks import run_mock_analysis_task

logger = logging.getLogger(__name__)

# Analysis task parameters
_TOKEN_PER_SEC: int = 50    # generation rate (tokens/s)
_TIMEOUT_SECS: int = 15     # hard deadline


class MockAnalysisNode(BaseNode):
    """Mock analysis node — opt-in streaming token generation."""

    node_name: str = "mock_analysis"

    def _create_node_output(self, task_result) -> dict:
        return {"result": task_result.result_str}

    def _log_completion(self, task_result, thread_id, node_id, elapsed_ms):
        logger.info(
            "[mock_analysis] completed thread_id=%s node_id=%s elapsed_ms=%d produced=%d",
            thread_id, node_id, elapsed_ms, task_result.produced,
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
            "[mock_analysis] symbol=%s token_per_sec=%d timeout_secs=%d thread_id=%s",
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
            return await run_mock_analysis_task(
                thread_id=thread_id_arg,
                task_id=task_id,
                node_execution_id=node_execution_id_arg,
                t0_node=None,  # BaseNode tracks t0 internally
            )

        return await self._execute_node_workflow(
            thread_id,
            parent_node_execution_id,
            node_input,
            task_runner,
            use_start_finish=False,
        )


_mock_analysis_instance = MockAnalysisNode()


async def mock_analysis_node(state: StreamRunState) -> dict:
    """LangGraph node function wrapper for MockAnalysisNode class."""
    return await _mock_analysis_instance(state)


__all__ = ["mock_analysis_node"]
