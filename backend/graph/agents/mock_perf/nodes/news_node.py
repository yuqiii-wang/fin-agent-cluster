"""news_node — mock news-fetching LangGraph node.

Reads the ``query_response`` from state (produced by ``mock_query_node``) and
calls the :class:`~backend.resources.news.client.NewsClient` to retrieve mock
news articles.  In production this would call a live news feed.

Node position in the pipeline:

    query_node → [news_node, stats_node] → merge_node  ← fan-out / fan-in

Refactored to use:
- ``@task`` from ``langgraph.func`` for the fetch computation so LangGraph
  checkpoints the result and avoids re-execution on resume.
- ``interrupt()`` from ``langgraph.types`` as the step-approval checkpoint,
  replacing the former ``check_node_cancel`` Redis signal.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone

from langgraph.func import task
from langgraph.types import interrupt

from backend.graph.agents.mock_perf.errors import NEWS_FAILED
from backend.graph.state import StreamRunState
from backend.graph.utils.execution_log import (
    finish_node_execution,
    start_node_execution,
    update_node_execution_status,
)
from backend.resources.news import NewsClient
from backend.sse_notifications import (
    TaskCancelledSignal,
    cancel_task,
    complete_task,
    create_task,
    fail_task,
)
from backend.sse_notifications.node import emit_node_status

logger = logging.getLogger(__name__)

_NODE_NAME: str = "mock_news"


@task
async def _fetch_news_task(
    thread_id: str,
    task_id: str,
    node_execution_id: int,
    node_id: str,
    symbol: str,
    limit: int,
) -> list[dict]:
    """LangGraph ``@task``: fetch news articles and emit task lifecycle events.

    Result is checkpointed — not re-executed on resume after a cancel/crash.

    Args:
        thread_id:         LangGraph thread UUID.
        task_id:           Task primary-key UUID.
        node_execution_id: FK to the parent ``node_executions`` row.
        node_id:           Node-level UUID for SSE events.
        symbol:            Ticker symbol to fetch news for.
        limit:             Maximum number of articles to retrieve.

    Returns:
        List of serialised :class:`~backend.resources.news.models.NewsArticle`
        dicts.
    """
    await create_task(
        thread_id,
        "MOCK_NEWS",
        node_execution_id,
        provider="mock",
        task_id=task_id,
        extra_payload={"node_id": node_id, "symbol": symbol},
    )

    try:
        client = NewsClient()
        response = await client.list_news(symbol=symbol, limit=limit)
        articles = [a.model_dump(mode="json") for a in response.items]
    except (asyncio.CancelledError, TaskCancelledSignal):
        await cancel_task(thread_id, task_id, "MOCK_NEWS")
        await update_node_execution_status(node_execution_id, "cancelled")
        await emit_node_status(thread_id, node_id, _NODE_NAME, "cancelled")
        raise asyncio.CancelledError()
    except Exception as exc:
        logger.exception("[mock_news] fetch error thread_id=%s: %s", thread_id, exc)
        await fail_task(thread_id, task_id, "MOCK_NEWS", str(exc), error_code=NEWS_FAILED)
        await emit_node_status(thread_id, node_id, _NODE_NAME, "failed")
        raise

    await complete_task(
        thread_id,
        task_id,
        "MOCK_NEWS",
        output={"symbol": symbol, "article_count": len(articles)},
    )
    return articles


async def mock_news_node(state: StreamRunState) -> dict:
    """Fetch mock news articles for the symbol from ``query_response``.

    Uses ``interrupt()`` as a step-approval checkpoint (replacing the former
    ``check_node_cancel`` Redis signal) then delegates the fetch to the
    ``@task``-decorated :func:`_fetch_news_task`.

    Args:
        state: :class:`~backend.graph.state.StreamRunState`.

    Returns:
        Partial state update with ``news_articles`` (list of serialised
        :class:`~backend.resources.news.models.NewsArticle` dicts).
    """
    thread_id: str = state["thread_id"]
    parent_node_execution_id: int | None = state.get("node_execution_id")
    query_response: dict = state.get("query_response") or {}
    symbol: str = query_response.get("symbol", "AAPL")
    limit: int = int(query_response.get("parameters", {}).get("limit_news", 5))

    # ── Step-approval interrupt (replaces check_node_cancel) ──────────────
    interrupt({"action": "step_approval", "node": _NODE_NAME, "thread_id": thread_id})

    node_id: str = str(uuid.uuid4())
    task_id: str = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()

    node_execution_id = await start_node_execution(
        thread_id,
        _NODE_NAME,
        {"symbol": symbol, "limit": limit, "node_id": node_id, "task_id": task_id},
        started_at,
        node_uuid=node_id,
        parent_node_execution_id=parent_node_execution_id,
    )
    await emit_node_status(thread_id, node_id, _NODE_NAME, "running")

    try:
        articles = await _fetch_news_task(thread_id, task_id, node_execution_id, node_id, symbol, limit)
    except asyncio.CancelledError:
        await update_node_execution_status(node_execution_id, "cancelled")
        await emit_node_status(thread_id, node_id, _NODE_NAME, "cancelled")
        raise
    except Exception:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        await finish_node_execution(node_execution_id, {}, elapsed_ms, status="failed")
        await emit_node_status(thread_id, node_id, _NODE_NAME, "failed")
        raise

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    await finish_node_execution(
        node_execution_id,
        {"symbol": symbol, "article_count": len(articles)},
        elapsed_ms,
    )
    await emit_node_status(thread_id, node_id, _NODE_NAME, "completed")

    logger.info(
        "[mock_news] fetched %d articles symbol=%s thread_id=%s node_id=%s elapsed_ms=%d",
        len(articles), symbol, thread_id, node_id, elapsed_ms,
    )
    return {"node_execution_id": node_execution_id, "news_articles": articles}


__all__ = ["mock_news_node"]
