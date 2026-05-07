"""node — thin LangGraph node function for the query stage.

Pipeline position::

    query_node → [news_node, stats_node] → merge_node  ← fan-out / fan-in

NOTE: ``interrupt()`` is intentionally NOT used here, for the same reason as
news_node and stats_node: an interrupt() checkpoint here would cause resume
to loop, as Command(resume=True) keeps returning to the same checkpoint.

The two inner tasks (:func:`run_analyze_user_query_task` and
:func:`run_add_static_query_metrics_task`) are ``@task``-decorated.
"""

from __future__ import annotations

import logging
import uuid

from backend.graph.agents._shared.base_node import BaseNode
from backend.graph.agents._shared.nodes.query_node.models import (
    QueryNodeInput,
    QueryNodeOutput,
)
from backend.graph.agents._shared.nodes.query_node.tasks.analyze_user_query.workflow import (
    run_analyze_user_query_task,
)
from backend.graph.agents._shared.nodes.query_node.tasks.add_static_query_metrics.workflow import (
    run_add_static_query_metrics_task,
)
from backend.graph.state import StreamRunState

logger = logging.getLogger(__name__)


class QueryNode(BaseNode):
    """Query node implementation."""

    node_name: str = "query"

    def _create_node_output(self, task_result):
        return QueryNodeOutput(query_response=task_result)

    def _log_completion(self, task_result, thread_id, node_id, elapsed_ms):
        logger.info(
            "[query] completed symbol=%s thread_id=%s node_id=%s elapsed_ms=%d",
            task_result.symbol, thread_id, node_id, elapsed_ms,
        )

    def _create_state_update(self, node_execution_id, node_id, task_id, task_result):
        return {
            "node_execution_id": node_execution_id,
            "node_id": node_id,
            "task_id": task_id,
            "query_response": task_result.as_dict(),
        }

    async def __call__(self, state: StreamRunState) -> dict:
        thread_id: str = state["thread_id"]
        parent_node_execution_id: int | None = state.get("node_execution_id")
        query: str = state.get("query", "")

        node_id: str = str(uuid.uuid4())
        task_id_1: str = str(uuid.uuid4())

        node_input = QueryNodeInput(query=query, node_id=node_id, task_id=task_id_1)

        async def task_runner(thread_id_arg, node_id_arg, node_execution_id_arg):
            analyzed = await run_analyze_user_query_task(
                thread_id_arg, task_id_1, node_execution_id_arg, node_id_arg, query=query,
            )
            task_id_2: str = str(uuid.uuid4())
            return await run_add_static_query_metrics_task(
                thread_id_arg, task_id_2, node_execution_id_arg, node_id_arg, query_output=analyzed,
            )

        return await self._execute_node_workflow(
            thread_id,
            [parent_node_execution_id] if parent_node_execution_id else [],
            node_input,
            task_runner,
        )


_query_node_instance = QueryNode()


async def query_node(state: StreamRunState) -> dict:
    """LangGraph node function wrapper for QueryNode class."""
    return await _query_node_instance(state)


__all__ = ["query_node"]

