"""node — thin LangGraph node function for the query stage.

Pipeline position::

    query_node → [news_node, stats_node] → merge_node  (fan-out / fan-in)

Durable-execution design
------------------------
``interrupt()`` fires first — establishing a checkpoint boundary.  All side
effects (UUID generation, DB tracking, task lifecycle) live inside the
``@task``-decorated :func:`_run_query_node` so they are checkpointed when the
task completes.  On resume, a completed ``_run_query_node`` is *replayed* from
the checkpoint — never re-executed — which eliminates the duplicate-node-id
fork seen in the UI.

The two inner tasks (:func:`run_analyze_user_query_task` and
:func:`run_add_static_query_metrics_task`) are also ``@task``-decorated, so
their individual results are nested-checkpointed inside the outer task.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from langgraph.func import task
from langgraph.types import interrupt

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
from backend.graph.utils.execution_log import update_node_execution_status
from backend.sse_notifications.node import emit_node_input, emit_node_output, emit_node_status

logger = logging.getLogger(__name__)

_NODE_NAME: str = "query"


@task
async def _run_query_node(
    thread_id: str,
    parent_node_execution_id: int | None,
    query: str,
) -> dict:
    """All query-node side effects: UUIDs, DB tracking, task calls, emit events.

    Wrapped in ``@task`` so the result is checkpointed on completion.
    On resume after a cancel, a completed task is replayed — never
    re-executed — keeping ``node_execution_id`` / ``node_id`` stable.

    Calls two inner ``@task`` functions in sequence:
    1. :func:`run_analyze_user_query_task` — LLM / mock parse.
    2. :func:`run_add_static_query_metrics_task` — append static commodity/crypto lists.
    """
    node_id: str = str(uuid.uuid4())
    task_id_1: str = str(uuid.uuid4())

    node_input = QueryNodeInput(query=query, node_id=node_id, task_id=task_id_1)
    node_execution_id, t0 = await emit_node_input(
        thread_id,
        _NODE_NAME,
        node_input.model_dump(),
        node_uuid=node_id,
        parent_node_execution_ids=[parent_node_execution_id] if parent_node_execution_id else [],
    )
    await emit_node_status(thread_id, node_id, _NODE_NAME, "running")

    try:
        analyzed = await run_analyze_user_query_task(
            thread_id, task_id_1, node_execution_id, node_id, query=query,
        )
        task_id_2: str = str(uuid.uuid4())
        final_output = await run_add_static_query_metrics_task(
            thread_id, task_id_2, node_execution_id, node_id, query_output=analyzed,
        )
    except asyncio.CancelledError:
        await update_node_execution_status(node_execution_id, "cancelled")
        await emit_node_status(thread_id, node_id, _NODE_NAME, "cancelled")
        raise
    except Exception:
        await update_node_execution_status(node_execution_id, "failed")
        await emit_node_status(thread_id, node_id, _NODE_NAME, "failed")
        raise

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    node_output = QueryNodeOutput(query_response=final_output)
    ended_at_ms = await emit_node_output(
        thread_id, _NODE_NAME, node_execution_id, node_output.model_dump(), elapsed_ms,
    )
    await emit_node_status(thread_id, node_id, _NODE_NAME, "completed", ended_at_ms=ended_at_ms)

    logger.info(
        "[query] completed symbol=%s thread_id=%s node_id=%s elapsed_ms=%d",
        final_output.symbol, thread_id, node_id, elapsed_ms,
    )
    return {
        "node_execution_id": node_execution_id,
        "node_id": node_id,
        "task_id": task_id_2,
        "query_response": final_output.as_dict(),
    }


async def query_node(state: StreamRunState) -> dict:
    """LangGraph node: checkpoint via ``interrupt()`` then delegate to ``@task``.

    Reading state fields before ``interrupt()`` has no side effects and is
    safe on resume.  All DB writes / SSE emits are inside :func:`_run_query_node`.

    Args:
        state: :class:`~backend.graph.state.StreamRunState`.

    Returns:
        Partial state update with ``node_execution_id``, ``node_id``,
        ``task_id``, and ``query_response``.
    """
    thread_id: str = state["thread_id"]
    parent_node_execution_id: int | None = state.get("node_execution_id")
    query: str = state.get("query", "")

    interrupt({"action": "step_approval", "node": _NODE_NAME, "thread_id": thread_id})

    return await _run_query_node(thread_id, parent_node_execution_id, query)


__all__ = ["query_node"]

