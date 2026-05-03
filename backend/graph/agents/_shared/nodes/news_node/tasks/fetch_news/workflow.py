"""workflow — async task function for the mock news fetch stage.

Encapsulates the full task lifecycle (``create_task`` → fetch → ``complete_task``)
so :func:`~backend.graph.agents._shared.nodes.news_node.node.mock_news_node`
stays a thin orchestrator.
"""

from __future__ import annotations

import asyncio
import logging

from langgraph.func import task

from backend.graph.agents._shared.errors import NEWS_FAILED
from backend.resources.news import NewsClient
from backend.sse_notifications import (
    TaskCancelledSignal,
    cancel_task,
    complete_task,
    create_task,
    fail_task,
)

logger = logging.getLogger(__name__)

_TASK_NAME: str = "MOCK_NEWS"


@task
async def run_fetch_news_task(
    thread_id: str,
    task_id: str,
    node_execution_id: int,
    node_id: str,
    *,
    symbol: str,
    limit: int,
) -> list[dict]:
    """Fetch mock news articles and manage full task lifecycle.

    LangGraph ``@task``: result is checkpointed — not re-executed on resume.

    Creates a DB task row, calls :class:`~backend.resources.news.client.NewsClient`,
    then marks the task completed.  Raises on cancel / error so the caller
    (:func:`~backend.graph.agents._shared.nodes.news_node.node.mock_news_node`)
    can handle node-level teardown.

    Args:
        thread_id:         LangGraph thread UUID.
        task_id:           Pre-generated task UUID.
        node_execution_id: FK to the parent ``node_executions`` row.
        node_id:           Node governance UUID.
        symbol:            Ticker symbol to fetch news for.
        limit:             Maximum number of articles to retrieve.

    Returns:
        List of serialised :class:`~backend.resources.news.models.NewsArticle` dicts.

    Raises:
        asyncio.CancelledError: When the task is cancelled (already cleaned up).
        Exception:              On fetch failure (already cleaned up).
    """
    await create_task(
        thread_id,
        _TASK_NAME,
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
        await cancel_task(thread_id, task_id, _TASK_NAME)
        raise asyncio.CancelledError()
    except Exception as exc:
        logger.exception("[fetch_news] error thread_id=%s: %s", thread_id, exc)
        await fail_task(thread_id, task_id, _TASK_NAME, str(exc), error_code=NEWS_FAILED)
        raise

    await complete_task(
        thread_id,
        task_id,
        _TASK_NAME,
        output={"symbol": symbol, "article_count": len(articles)},
    )
    return articles


__all__ = ["run_fetch_news_task"]
