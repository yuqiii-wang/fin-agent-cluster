"""fin_analyst_runner — LangGraph leaf node for the financial analysis workflow.

Architecture
------------
This node is activated for all queries that are NOT the perf-test trigger phrase.
The outer graph routes to this sub-graph for any genuine financial analysis query.

The node uses ``interrupt()`` as a step-approval checkpoint (auto-approved for now)
before delegating analysis work.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from langgraph.types import interrupt

from backend.graph.agents._shared.base_node import BaseNode
from backend.graph.agents.fin_analyst.errors import FIN_ANALYST_FAILED
from backend.graph.agents.fin_analyst.models import FinAnalystOutput
from backend.graph.state import StreamRunState

logger = logging.getLogger(__name__)


class FinAnalystNode(BaseNode):
    """Financial analyst node implementation."""

    node_name: str = "fin_analyst_runner"

    def _create_node_output(self, task_result) -> dict:
        return task_result.as_dict()

    def _log_completion(self, task_result, thread_id, node_id, elapsed_ms):
        logger.info(
            "[fin_analyst] completed thread_id=%s node_id=%s elapsed_ms=%d",
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
            "task_id": task_id,
            "result": task_result.summary,
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
            from backend.sse_notifications import (
                TaskCancelledSignal,
                cancel_task,
                complete_task,
                create_task,
                fail_task,
            )

            await create_task(
                thread_id_arg,
                "FIN_ANALYST_ANALYSIS",
                node_execution_id_arg,
                provider="stub",
                task_id=task_id,
                extra_payload={"node_id": node_id_arg},
            )

            try:
                # TODO: replace with real market data + LLM pipeline
                output = FinAnalystOutput(
                    summary=f"[stub] Received query: {query!r}. Full analysis pending implementation.",
                    confidence=0.0,
                )
            except (asyncio.CancelledError, TaskCancelledSignal):
                await cancel_task(thread_id_arg, task_id, "FIN_ANALYST_ANALYSIS")
                raise asyncio.CancelledError()
            except Exception as exc:
                logger.exception("[fin_analyst] analysis error thread_id=%s: %s", thread_id_arg, exc)
                await fail_task(
                    thread_id_arg, task_id, "FIN_ANALYST_ANALYSIS", str(exc),
                    error_code=FIN_ANALYST_FAILED,
                )
                raise

            await complete_task(thread_id_arg, task_id, "FIN_ANALYST_ANALYSIS", output.as_dict())
            return output

        return await self._execute_node_workflow(
            thread_id,
            parent_node_execution_id,
            node_input,
            task_runner,
            pre_execute_hook,
            use_start_finish=True,
        )


_fin_analyst_instance = FinAnalystNode()


async def fin_analyst_runner(state: StreamRunState) -> dict:
    """LangGraph node function wrapper for FinAnalystNode class."""
    return await _fin_analyst_instance(state)


__all__ = ["fin_analyst_runner"]
