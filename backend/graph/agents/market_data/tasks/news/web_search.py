"""run_web_search: execute named news queries for market_data_collector.

Input:  NewsClient, ticker, label, q_text, task_id, thread_id
Output: NewsRawResults"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from backend.graph.agents.market_data.models.news import ArticleSummary, NewsRawResults
from backend.graph.agents.task_keys import md_web_search
from backend.graph.utils.news_stats import transform_news_to_stats
from backend.graph.utils.pdf_parser import fetch_and_parse_pdf, is_pdf_url
from backend.sse_notifications import complete_task, fail_task
from backend.resource_api.news_api.client import NewsClient
from backend.resource_api.news_api.models import NewsArticle, NewsQuery, NewsResult

logger = logging.getLogger(__name__)

# How long to wait before retrying a zero-article result (seconds).
_ZERO_ARTICLE_RETRY_DELAY = 30




async def _enrich_article_with_pdf(article: NewsArticle) -> NewsArticle:
    """If the article URL is a PDF, download and inject extracted text as summary.

    Args:
        article: Source news article.

    Returns:
        The same article with ``summary`` replaced by extracted PDF text when
        available, otherwise the original article unchanged.
    """
    if not article.url or not is_pdf_url(article.url):
        return article
    logger.info("[news tasks] financial report URL appears to be a PDF — parsing: %s", article.url)
    pdf_text = await fetch_and_parse_pdf(article.url)
    if pdf_text:
        return article.model_copy(update={"summary": pdf_text[:4000]})
    return article


async def run_web_search(
    nclient: NewsClient,
    ticker: str,
    label: str,
    q_text: str,
    task_id: int,
    thread_id: str,
) -> NewsRawResults:
    """Execute one named news query via web search and persist stats to DB.

    The task entry must already exist (created by the caller so all task IDs
    are pre-registered before the concurrent gather).

    Special behaviour:
    - ``financial_report``: fetches only the single most recent result and
      attempts to extract full text when the article URL is a PDF.
    - Zero-article result: waits ``_ZERO_ARTICLE_RETRY_DELAY`` seconds then
      retries with ``alpha_vantage`` as an alternative provider.

    Args:
        nclient:   Shared NewsClient instance.
        ticker:    Primary ticker for the stats attribution.
        label:     Short key used in task and log naming, e.g. 'financial_report'.
        q_text:    Full search query string.
        task_id:   Pre-registered task id for status updates.
        thread_id: LangGraph thread id.

    Returns:
        :class:`WebSearchResult` with metadata (results persisted to DB only).
    """
    is_financial_report = label in ("financial_report", "query_financial_report")

    async def _do_fetch(source: str, use_cache: bool = True) -> tuple[NewsResult, Optional[int]]:
        params: dict = {"limit": 1} if is_financial_report else {"limit": 20}
        return await nclient.fetch(
            NewsQuery(
                method="topic_news",
                query=q_text,
                params=params,
                thread_id=thread_id,
                node_name="market_data_collector",
            ),
            source=source,  # type: ignore[arg-type]
            use_cache=use_cache,
            cache_ttl_hours=4.0,
        )

    try:
        ws_result, ws_raw_id = await _do_fetch("web_search")

        # Zero-article guard: wait and retry with a different provider.
        if not ws_result.articles:
            logger.info(
                "[news tasks] web_search[%s] returned 0 articles — retrying in %ds with alpha_vantage",
                label, _ZERO_ARTICLE_RETRY_DELAY,
            )
            await asyncio.sleep(_ZERO_ARTICLE_RETRY_DELAY)
            ws_result, ws_raw_id = await _do_fetch("alpha_vantage", use_cache=False)

        # For financial reports: attempt PDF extraction on the single article.
        if is_financial_report and ws_result.articles:
            ws_result.articles[0] = await _enrich_article_with_pdf(ws_result.articles[0])

        summaries: list[str] = []
        if ws_raw_id is not None:
            _count, summaries = await transform_news_to_stats(
                ws_raw_id, ws_result, ticker,
                thread_id=thread_id, task_id=task_id, task_key=md_web_search(label),
            )

        article_count = len(ws_result.articles) if ws_result.articles else 0
        source = ws_result.source or "web_search"
        await complete_task(
            thread_id, task_id, md_web_search(label),
            {"article_count": article_count, "source": source, "query": q_text},
        )
        articles = [
            ArticleSummary(
                title=a.title,
                source_name=a.source_name or "",
                published_at=str(a.published_at or "")[:10] or None,
            )
            for a in (ws_result.articles or [])
        ]
        return NewsRawResults(
            ticker=ticker, query_key=label, query=q_text,
            articles=articles, source=source,
        )
    except Exception as exc:
        logger.warning("[news tasks] web_search[%s] failed: %s", label, exc)
        await fail_task(thread_id, task_id, md_web_search(label), str(exc))
        return NewsRawResults(ticker=ticker, query_key=label, query=q_text, error=str(exc))
