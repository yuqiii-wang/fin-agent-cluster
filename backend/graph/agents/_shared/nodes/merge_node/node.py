"""node — thin LangGraph node function for the merge (fan-in) stage.

Node position in the pipeline::

    query_node → [news_node, stats_node] → merge_node → analysis_node → END

Fan-in edge topology: receives ``parent_node_execution_ids`` from both
``news_node`` and ``stats_node`` so the graph visualisation shows two
inbound edges.

Durable-execution design
------------------------
``interrupt()`` fires first — establishing a checkpoint boundary.  All side
effects (UUID generation, DB tracking, task lifecycle) live inside the
``@task``-decorated :func:`_run_merge_node` so they are checkpointed when the
task completes.  On resume, a completed ``_run_merge_node`` is *replayed* from
the checkpoint — never re-executed — which eliminates the duplicate-node-id
fork seen in the UI.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from langgraph.func import task
from langgraph.types import interrupt

from backend.graph.agents._shared.nodes.merge_node.models import (
    MergeNodeInput,
    MergeNodeOutput,
)
from backend.graph.agents._shared.nodes.merge_node.tasks.merge import run_merge_task
from backend.graph.state import StreamRunState
from backend.graph.utils.execution_log import update_node_execution_status
from backend.sse_notifications.node import (
    emit_node_input,
    emit_node_output,
    emit_node_status,
)

logger = logging.getLogger(__name__)

_NODE_NAME: str = "merge"


@task
async def _run_merge_node(
    thread_id: str,
    parent_ids: list[int],
    news_articles: list[dict],
    stats_records: list[dict],
    symbol: str,
    analysis_type: str,
    time_horizon: str,
) -> dict:
    """All merge-node side effects: UUIDs, DB tracking, merge task, emit events.

    Wrapped in ``@task`` so the result is checkpointed on completion.
    On resume after a cancel, a completed task is replayed — never
    re-executed — keeping ``node_execution_id`` / ``node_id`` stable.
    """
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
    node_execution_id, t0 = await emit_node_input(
        thread_id,
        _NODE_NAME,
        node_input.model_dump(),
        node_uuid=node_id,
        parent_node_execution_ids=parent_ids,
    )
    await emit_node_status(thread_id, node_id, _NODE_NAME, "running")

    meta: dict = {
        "symbol": symbol,
        "analysis_type": analysis_type,
        "time_horizon": time_horizon,
    }

    try:
        merged = await run_merge_task(
            thread_id, task_id, node_execution_id, node_id,
            news_json=news_articles,
            stats_json=stats_records,
            meta=meta,
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
    merged_dict = merged.as_dict()
    node_output = MergeNodeOutput(
        symbol=symbol,
        news_count=len(news_articles),
        stats_count=len(stats_records),
        merged_keys=list(merged_dict.keys()),
    )
    ended_at_ms = await emit_node_output(
        thread_id, _NODE_NAME, node_execution_id, node_output.model_dump(), elapsed_ms,
    )
    await emit_node_status(thread_id, node_id, _NODE_NAME, "completed", ended_at_ms=ended_at_ms)

    logger.info(
        "[merge] merged symbol=%s articles=%d records=%d thread_id=%s node_id=%s elapsed_ms=%d",
        symbol, len(news_articles), len(stats_records), thread_id, node_id, elapsed_ms,
    )
    return {
        "node_execution_id": node_execution_id,
        "node_id": node_id,
        "task_id": task_id,
        "merged_analysis": merged_dict,
    }


async def merge_node(state: StreamRunState) -> dict:
    """LangGraph node: checkpoint via ``interrupt()`` then delegate to ``@task``.

    Reading state fields before ``interrupt()`` has no side effects and is
    safe on resume.  All DB writes / SSE emits are inside :func:`_run_merge_node`.

    Args:
        state: :class:`~backend.graph.state.StreamRunState` carrying
               ``news_articles``, ``stats_records``, ``news_node_execution_id``,
               and ``stats_node_execution_id`` from upstream nodes.

    Returns:
        Partial state update with ``node_execution_id``, ``node_id``,
        ``task_id``, and ``merged_analysis``.
    """
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

    interrupt({"action": "step_approval", "node": _NODE_NAME, "thread_id": thread_id})

    return await _run_merge_node(
        thread_id, parent_ids, news_articles, stats_records,
        symbol, analysis_type, time_horizon,
    )


__all__ = ["merge_node"]

logger = logging.getLogger(__name__)

_NODE_NAME: str = "merge"


async def merge_node(state: StreamRunState) -> dict:
    """Aggregate news + stats into a single ``merged_analysis`` dict.

    Delegates task lifecycle (create/complete/fail/cancel) to
    :func:`~backend.graph.agents._shared.nodes.merge_node.tasks.merge.workflow.run_merge_task`
    so this node only handles node-level I/O recording and cancel checks.

    Reads ``news_node_execution_id`` and ``stats_node_execution_id`` from
    state so that :func:`~backend.sse_notifications.node_io.emit_node_input`
    can record both parent edges in the graph visualisation.

    Args:
        state: :class:`~backend.graph.state.StreamRunState` carrying
               ``news_articles``, ``stats_records``, ``news_node_execution_id``,
               and ``stats_node_execution_id`` from upstream nodes.

    Returns:
        Partial state update with ``node_execution_id``, ``node_id``,
        ``task_id``, and ``merged_analysis``.
    """
    thread_id: str = state["thread_id"]
    news_exec_id: int | None = state.get("news_node_execution_id")
    stats_exec_id: int | None = state.get("stats_node_execution_id")
    news_articles: list[dict] = state.get("news_articles") or []
    stats_records: list[dict] = state.get("stats_records") or []
    query_response: dict = state.get("query_response") or {}

    parent_ids: list[int] = [x for x in [news_exec_id, stats_exec_id] if x is not None]

    node_id: str = str(uuid.uuid4())
    task_id: str = str(uuid.uuid4())

    symbol: str = query_response.get("symbol", "AAPL")

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

    # ── Step-approval interrupt (replaces check_node_cancel) ──────────────
    interrupt({"action": "step_approval", "node": _NODE_NAME, "thread_id": thread_id})

    node_execution_id, t0 = await emit_node_input(
        thread_id,
        _NODE_NAME,
        node_input.model_dump(),
        node_uuid=node_id,
        parent_node_execution_ids=parent_ids,
    )
    await emit_node_status(thread_id, node_id, _NODE_NAME, "running")

    meta: dict = {
        "symbol": symbol,
        "analysis_type": query_response.get("analysis_type", "comprehensive"),
        "time_horizon": query_response.get("time_horizon", "1w"),
    }

    try:
        merged = await run_merge_task(
            thread_id,
            task_id,
            node_execution_id,
            node_id,
            news_json=news_articles,
            stats_json=stats_records,
            meta=meta,
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
    merged_dict = merged.as_dict()
    node_output = MergeNodeOutput(
        symbol=symbol,
        news_count=len(news_articles),
        stats_count=len(stats_records),
        merged_keys=list(merged_dict.keys()),
    )
    ended_at_ms = await emit_node_output(thread_id, _NODE_NAME, node_execution_id, node_output.model_dump(), elapsed_ms)
    await emit_node_status(thread_id, node_id, _NODE_NAME, "completed", ended_at_ms=ended_at_ms)

    logger.info(
        "[merge] merged symbol=%s articles=%d records=%d thread_id=%s node_id=%s elapsed_ms=%d",
        symbol, len(news_articles), len(stats_records), thread_id, node_id, elapsed_ms,
    )
    return {
        "node_execution_id": node_execution_id,
        "node_id": node_id,
        "task_id": task_id,
        "merged_analysis": merged_dict,
    }


__all__ = ["merge_node"]
