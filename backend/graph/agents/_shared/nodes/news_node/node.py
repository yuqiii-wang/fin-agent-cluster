"""node — thin LangGraph node function for the news fetch stage.

Node position in the pipeline::

    query_node → [news_node, stats_node] → merge_node  ← fan-out / fan-in

Durable-execution design
------------------------
Side effects (UUID generation, DB tracking, task lifecycle) live inside the
``@task``-decorated :func:`_run_news_node` so they are checkpointed when the
task completes.  On resume, a completed ``_run_news_node`` is *replayed* from
the checkpoint — never re-executed — which eliminates the duplicate-node-id
fork seen in the UI.

NOTE: ``interrupt()`` is intentionally NOT used here.  In a parallel fan-out
(news_node + stats_node both scheduled concurrently), simultaneous interrupt()
calls share the same LangGraph checkpoint.  Each successive ``Command(resume=True)``
loads the original shared checkpoint where neither @task has run yet, causing
each fan-out node to re-execute on every subsequent resume pass (duplicate
node_execution_ids in the UI).  Removing interrupt() from these fast fan-out
nodes lets the StateGraph's standard node-completion checkpointing handle
deduplication correctly.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from langgraph.func import task

from backend.graph.agents._shared.nodes.news_node.models import NewsNodeInput, NewsNodeOutput
from backend.graph.agents._shared.nodes.news_node.tasks import run_fetch_news_task
from backend.graph.state import StreamRunState
from backend.graph.utils.execution_log import update_node_execution_status
from backend.sse_notifications.node import emit_node_input, emit_node_output, emit_node_status

logger = logging.getLogger(__name__)

_NODE_NAME: str = "mock_news"


@task
async def _run_news_node(
    thread_id: str,
    parent_node_execution_id: int | None,
    symbol: str,
    limit: int,
) -> dict:
    """All news-node side effects: UUIDs, DB tracking, fetch, emit events.

    Wrapped in ``@task`` so the result is checkpointed on completion.
    On resume after a cancel, a completed task is replayed — never
    re-executed — keeping ``node_execution_id`` / ``node_id`` stable.
    """
    node_id: str = str(uuid.uuid4())
    task_id: str = str(uuid.uuid4())

    node_input = NewsNodeInput(symbol=symbol, limit=limit, node_id=node_id, task_id=task_id)
    node_execution_id, t0 = await emit_node_input(
        thread_id,
        _NODE_NAME,
        node_input.model_dump(),
        node_uuid=node_id,
        parent_node_execution_ids=[parent_node_execution_id] if parent_node_execution_id else [],
    )
    await emit_node_status(thread_id, node_id, _NODE_NAME, "running")

    try:
        articles = await run_fetch_news_task(
            thread_id, task_id, node_execution_id, node_id,
            symbol=symbol, limit=limit,
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
    node_output = NewsNodeOutput(symbol=symbol, article_count=len(articles))
    ended_at_ms = await emit_node_output(
        thread_id, _NODE_NAME, node_execution_id, node_output.model_dump(), elapsed_ms,
    )
    await emit_node_status(thread_id, node_id, _NODE_NAME, "completed", ended_at_ms=ended_at_ms)

    logger.info(
        "[mock_news] fetched %d articles symbol=%s thread_id=%s node_id=%s elapsed_ms=%d",
        len(articles), symbol, thread_id, node_id, elapsed_ms,
    )
    return {"news_node_execution_id": node_execution_id, "news_articles": articles}


async def mock_news_node(state: StreamRunState) -> dict:
    """LangGraph node: delegate directly to ``@task`` (no interrupt checkpoint).

    All DB writes / SSE emits are inside :func:`_run_news_node`.
    ``interrupt()`` is intentionally absent — see module docstring for rationale.

    Args:
        state: :class:`~backend.graph.state.StreamRunState`.

    Returns:
        Partial state update with ``news_node_execution_id`` and
        ``news_articles``.
    """
    thread_id: str = state["thread_id"]
    parent_node_execution_id: int | None = state.get("node_execution_id")
    query_response: dict = state.get("query_response") or {}
    symbol: str = query_response.get("symbol", "AAPL")
    limit: int = int(query_response.get("parameters", {}).get("limit_news", 5))

    return await _run_news_node(thread_id, parent_node_execution_id, symbol, limit)


__all__ = ["mock_news_node"]

