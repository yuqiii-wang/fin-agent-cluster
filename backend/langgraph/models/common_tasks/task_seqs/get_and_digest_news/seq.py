"""get_and_digest_news — TaskSeq pipeline: fetch raw news then LLM-digest into news_stats.

Orchestration
-------------
1. ``get_news``              — fetch by requesting url/news provider, e.g., 
    FinancialModelingPrep news API or DuckDuckGo Search API, or just input from the previous task.
    Hard failure: if this step fails, the whole pipeline fails and raises.
2. ``do_summary`` ┐ parallel — LLM-classify each article (soft failure).
   ``do_emb``     ┘           embed title+content of each article (soft failure).
3. ``digest_news``           — read from ``input_raw``, combine summaries+embeddings,
                               upsert to ``news_stats``, render Markdown.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from backend.langgraph.models.common_tasks.errors.codes import (
    NEWS_TASK_EMB_WARN,
    NEWS_TASK_SUMMARY_WARN,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_digest_news.digest_news import (
    DigestNewsInput,
    DigestNewsOutput,
    digest_news,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_digest_news.do_emb import (
    DoEmbInput,
    DoEmbOutput,
    do_emb,
)
from backend.langgraph.models.common_tasks.do_summary import (
    DoSummaryInput,
    DoSummaryOutput,
    do_summary,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_digest_news.get_news import (
    GetNewsInput,
    GetNewsOutput,
    get_news,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_digest_news.models import (
    GetAndDigestNewsInput,
    GetAndDigestNewsOutput,
)
from backend.langgraph.models.models import NodeContext
from backend.langgraph.models.task_seq import TaskSeq

logger = logging.getLogger(__name__)

_SEQ_NAME = "get_and_digest_news"


async def _pipeline(
    run_task_fn: Callable[..., Awaitable[Any]],
    ctx: NodeContext,
    seq_input: GetAndDigestNewsInput,
) -> GetAndDigestNewsOutput:
    """Run get_news → (do_summary ‖ do_emb) → digest_news.

    ``do_summary`` and ``do_emb`` run in parallel after ``get_news`` completes.
    Both are soft-failure tasks: exceptions log a warning and the pipeline
    continues with empty intermediate output so that ``digest_news`` can still
    store raw articles without enrichment.

    Args:
        run_task_fn: Bound ``self.run_task`` from the hosting node.
        ctx:         Current node context.
        seq_input:   Typed pipeline input.

    Returns:
        Combined output from all four tasks.
    """
    # 1. get_news — hard failure (propagates)
    gn_result = await run_task_fn(
        get_news,
        ctx,
        GetNewsInput(
            symbol=seq_input.symbol,
            topics=seq_input.topics,
            from_dt=seq_input.from_dt,
            to_dt=seq_input.to_dt,
            news_limit=seq_input.news_limit,
        ),
    )
    gn_output: GetNewsOutput = gn_result.content
    articles_json = [a.model_dump(mode="json") for a in gn_output.news_articles]

    # 2. do_summary ‖ do_emb — run in parallel, both are soft failures
    summary_coro = run_task_fn(
        do_summary,
        ctx,
        DoSummaryInput(
            input_raw_id=gn_output.input_raw_id,
            news_articles=articles_json,
            detailed_prompt=seq_input.detailed_prompt,
        ),
    )
    emb_coro = run_task_fn(
        do_emb,
        ctx,
        DoEmbInput(
            input_raw_id=gn_output.input_raw_id,
            news_articles=articles_json,
        ),
    )
    summary_result, emb_result = await asyncio.gather(
        summary_coro, emb_coro, return_exceptions=True
    )

    summary_output = DoSummaryOutput()
    if isinstance(summary_result, BaseException):
        logger.warning(
            "[%s] do_summary failed (soft), continuing without LLM summaries: %s",
            NEWS_TASK_SUMMARY_WARN, summary_result,
        )
    else:
        summary_output = summary_result.content

    emb_output = DoEmbOutput()
    if isinstance(emb_result, BaseException):
        logger.warning(
            "[%s] do_emb failed (soft), continuing without embeddings: %s",
            NEWS_TASK_EMB_WARN, emb_result,
        )
    else:
        emb_output = emb_result.content

    all_from_cache = gn_output.from_cache and summary_output.from_cache and emb_output.from_cache

    # 3. digest_news — reads from DB, combines enrichment, upserts, renders Markdown
    dn_result = await run_task_fn(
        digest_news,
        ctx,
        DigestNewsInput(
            input_raw_id=gn_output.input_raw_id,
            source_filter=gn_output.source,
            summaries=summary_output.summaries,
            embeddings=emb_output.embeddings,
            from_cache=all_from_cache,
        ),
    )

    return GetAndDigestNewsOutput(
        get_news=gn_output,
        do_summary=summary_output,
        do_emb=emb_output,
        digest_news=dn_result.content,
    )


get_and_digest_news: TaskSeq[GetAndDigestNewsInput, GetAndDigestNewsOutput] = TaskSeq(
    name=_SEQ_NAME,
    description=(
        "Sequential pipeline: fetch news articles (FMP) and web-search info (DDGS) "
        "for a symbol/topic/datetime window (get_news), LLM-classify each article "
        "(do_summary, soft failure), embed the AI summaries (do_emb, soft failure), "
        "then read from fin_markets.input_raw, combine enrichment, upsert to "
        "fin_markets.news_stats, and render a Markdown digest (digest_news)."
    ),
    tasks=[get_news, do_summary, do_emb, digest_news],
    input_type=GetAndDigestNewsInput,
    output_type=GetAndDigestNewsOutput,
    pipeline_fn=_pipeline,
)

__all__ = ["get_and_digest_news"]
