"""digest_news — NodeTask: upsert enriched news rows to news_stats and render Markdown digest.

Reads raw articles from ``fin_markets.news_raw`` by ``news_raw_id`` and ``source_filter``
(default ``"fmp"``), combines each article with pre-computed LLM summaries from
``do_summary`` and vector embeddings from ``do_emb``, upserts rows to
``fin_markets.news_stats``, then queries the same ``news_raw_id`` from
``news_stats`` to build a Markdown-formatted digest list.

One-to-many relationship
------------------------
One ``news_raw`` row (the get_news cache entry) → many ``news_stats`` rows
(one per article).  The Markdown output renders all ``news_stats`` rows that
share the same ``news_raw_id``.

Execution layers
----------------
LangGraph layer (``_digest_news_task`` decorated with ``@task``):
    Delegates to the Celery completion worker.

Celery layer (``_handler``):
    1. Read articles from ``news_raw`` by ``news_raw_id``.
    2. Filter by ``source_filter`` (``"fmp"`` → ``news_articles`` list).
    3. For each article: upsert to ``news_stats`` using available enrichment.
    4. Query ``news_stats WHERE news_raw_id = ?`` and render Markdown.

Public exports
--------------
``digest_news``     — ``NodeTask`` instance.
``DigestNewsInput`` — Input model.
``DigestNewsOutput``— Output model (includes ``markdown`` field).
``HANDLERS``        — dict slice for registration in ``backend.langgraph.nodes.HANDLERS``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any

from langgraph.func import task
from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.db.postgres import raw_conn
from backend.db.postgres.queries.fin_markets_news import NewsRawSQL, NewsStatsSQL
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.errors.codes import NEWS_TASK_DIGEST_ERROR
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask
from backend.resources.news.models import NewsArticle

logger = logging.getLogger(__name__)

_TASK_NAME = "digest_news"


def _url_hash(url: str | None, title: str) -> str:
    """Compute sha256 of URL, falling back to title when url is absent."""
    key = url or title
    return hashlib.sha256(key.encode()).hexdigest()


def _format_published(published_at: Any) -> str:
    """Format a published_at value to a YYYY-MM-DD string for Markdown display."""
    if published_at is None:
        return ""
    if isinstance(published_at, datetime):
        return published_at.strftime("%Y-%m-%d")
    return str(published_at)[:10]


def _build_markdown(rows: list[Any], symbol: str | None) -> str:
    """Build a Markdown-formatted digest list from ``news_stats`` rows.

    Args:
        rows:   Sequence of DB rows from ``fin_markets.news_stats``, each
                supporting dict-like column access.
        symbol: Equity ticker for the header line, or ``None``.

    Returns:
        Markdown string ready for direct rendering.
    """
    if not rows:
        return "## News Digest\n\n_No news articles found._"

    header = f"## News Digest{f' — {symbol}' if symbol else ''}"
    parts = [header]

    for i, row in enumerate(rows, 1):
        title: str = row["title"] or ""
        url: str | None = row["url"]
        sentiment: str | None = row["sentiment_level"]
        topic: str | None = row["topic"]
        published: Any = row["published_at"]
        summary: str | None = row["summary"]
        source_name: str | None = row["source_name"]
        raw_tags: Any = row["tags"] or []

        title_md = f"[{title}]({url})" if url else title
        parts.append(f"\n### {i}. {title_md}")

        meta_parts: list[str] = []
        if source_name:
            meta_parts.append(f"**Source**: {source_name}")
        pub_str = _format_published(published)
        if pub_str:
            meta_parts.append(f"**Published**: {pub_str}")
        if sentiment:
            meta_parts.append(f"**Sentiment**: {sentiment.replace('_', ' ')}")
        if topic:
            meta_parts.append(f"**Topic**: {topic}")
        if meta_parts:
            parts.append(" | ".join(meta_parts))

        tags: list[str] = list(raw_tags) if raw_tags else []
        if tags:
            parts.append(f"**Tags**: {', '.join(tags)}")

        if summary:
            parts.append(f"\n> {summary}")

        parts.append("\n---")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class DigestNewsInput(BaseModel):
    """Input for the digest_news task.

    Attributes:
        news_raw_id:   PK of the ``news_raw`` row to read articles from.
        source_filter: Provider type to process (``"fmp"`` or ``"ddgs"`` →
                       ``news_articles`` list from the raw output).  Future
                       providers can be added here.
        summaries:     Mapping of ``url_hash`` → serialised :class:`SummaryRecord`
                       from ``do_summary``.  Empty when ``do_summary`` failed
                       or was skipped.
        embeddings:    Mapping of ``url_hash`` → 768-dim embedding vector from
                       ``do_emb``.  Empty when ``do_emb`` failed or was skipped.
        from_cache:    ``True`` when all upstream tasks (get_news, do_summary,
                       do_emb) were served from cache; triggers a fast-path
                       read of existing ``news_stats`` rows without re-upserting.
    """

    news_raw_id: int | None = Field(default=None, description="PK of the news_raw row.")
    source_filter: str = Field(default="fmp", description="Provider type to process.")
    summaries: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="url_hash -> SummaryRecord dict from do_summary output.",
    )
    embeddings: dict[str, list[float]] = Field(
        default_factory=dict,
        description="url_hash -> embedding vector from do_emb output.",
    )
    from_cache: bool = Field(
        default=False,
        description="True when all upstream tasks were from cache; enables fast-path read.",
    )


class DigestNewsOutput(BaseModel):
    """Output from the digest_news task.

    Attributes:
        upserted_ids:  ``news_stats`` row IDs that were inserted or updated.
        skipped_count: Number of articles skipped due to DB errors.
        markdown:      Markdown-formatted list of all ``news_stats`` rows that
                       share the same ``news_raw_id`` (one-to-many render).
        from_cache:    ``True`` when existing ``news_stats`` rows were reused
                       without re-upserting (all upstream tasks were from cache).
    """

    upserted_ids: list[int] = Field(default_factory=list)
    skipped_count: int = Field(default=0)
    markdown: str = Field(default="", description="Markdown digest of news_stats rows.")
    from_cache: bool = Field(default=False, description="True when served from existing news_stats rows.")


# ---------------------------------------------------------------------------
# Celery handler
# ---------------------------------------------------------------------------


async def _handler(payload: dict) -> dict:
    """Celery-layer business logic for digest_news.

    Args:
        payload: Serialised :class:`DigestNewsInput` fields.

    Returns:
        Serialised :class:`DigestNewsOutput` dict.
    """
    inp = DigestNewsInput.model_validate(payload)

    if inp.news_raw_id is None:
        return DigestNewsOutput().model_dump(mode="json")

    # 1. Read articles from news_raw by news_raw_id
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(NewsRawSQL.GET_BY_ID, (inp.news_raw_id,))
        raw_row = await cur.fetchone()

    if not raw_row:
        logger.error(
            "[%s] digest_news: news_raw id=%s not found",
            NEWS_TASK_DIGEST_ERROR, inp.news_raw_id,
        )
        return DigestNewsOutput().model_dump(mode="json")

    raw_output: dict = raw_row["output"]

    # 2. Extract articles from news_raw output.
    # All news providers (fmp, ddgs, mock, …) store articles under "news_articles".
    _KNOWN_NEWS_SOURCES = {"fmp", "ddgs", "mock"}
    if inp.source_filter not in _KNOWN_NEWS_SOURCES:
        logger.error(
            "[%s] digest_news: unsupported source_filter=%r",
            NEWS_TASK_DIGEST_ERROR, inp.source_filter,
        )
    articles = [
        NewsArticle.model_validate(a) for a in raw_output.get("news_articles", [])
    ]

    if not articles:
        return DigestNewsOutput().model_dump(mode="json")

    # Derive symbol for Markdown header from first article that has one
    symbol: str | None = next((a.symbol for a in articles if a.symbol), None)

    # 3. Upsert each article to news_stats
    upserted_ids: list[int] = []
    skipped_count = 0

    for article in articles:
        url_hash_val = _url_hash(article.url, article.title)

        summary_record: dict[str, Any] | None = inp.summaries.get(url_hash_val)
        embedding: list[float] | None = inp.embeddings.get(url_hash_val)

        summary: str | None = summary_record.get("summary") if summary_record else None
        sentiment_level: str | None = summary_record.get("sentiment_level") if summary_record else None
        topic: str | None = summary_record.get("topic") if summary_record else None
        tags: list[str] = summary_record.get("tags", []) if summary_record else []

        try:
            async with raw_conn() as conn:
                await conn.execute(
                    NewsStatsSQL.UPSERT,
                    (
                        inp.news_raw_id,
                        article.source,
                        article.symbol,
                        article.url,
                        url_hash_val,
                        article.title,
                        article.content,
                        article.source_name,
                        article.published_at,
                        summary,
                        json.dumps(embedding) if embedding is not None else None,
                        sentiment_level,
                        topic,
                        tags,
                    ),
                )
                cur2 = await conn.execute(
                    "SELECT id FROM fin_markets.news_stats WHERE source = %s AND url_hash = %s",
                    (article.source, url_hash_val),
                )
                id_row = await cur2.fetchone()
                if id_row:
                    upserted_ids.append(id_row["id"])
        except Exception as exc:
            logger.error(
                "[%s] digest_news DB upsert failed item=%r: %s",
                NEWS_TASK_DIGEST_ERROR, article.title[:80], exc,
            )
            skipped_count += 1

    # 4. Query news_stats by news_raw_id and render Markdown (one-to-many)
    markdown = ""
    try:
        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(NewsStatsSQL.GET_BY_NEWS_RAW_ID, (inp.news_raw_id,))
            stats_rows = await cur.fetchall()
        markdown = _build_markdown(stats_rows, symbol)
    except Exception as exc:
        logger.error(
            "[%s] digest_news Markdown render failed news_raw_id=%s: %s",
            NEWS_TASK_DIGEST_ERROR, inp.news_raw_id, exc,
        )

    return DigestNewsOutput(
        upserted_ids=upserted_ids,
        skipped_count=skipped_count,
        markdown=markdown,
        from_cache=False,
    ).model_dump(mode="json")


# ---------------------------------------------------------------------------
# LangGraph layer -- @task orchestration
# ---------------------------------------------------------------------------


@task
async def _digest_news_task(
    task_input: TaskInput[DigestNewsInput],
) -> TaskOutput[DigestNewsOutput]:
    """LangGraph @task: delegates digest_news to the Celery completion worker.

    Fast path (from_cache=True): if all upstream tasks were from cache and
    ``news_stats`` rows already exist for this ``news_raw_id``, reuses existing
    rows to build the Markdown without re-upserting (ToolCall task record).

    Normal path: creates a Markdown task, delegates to the Celery completion
    worker, and returns the upserted output.

    Args:
        task_input: Typed envelope with :class:`~backend.langgraph.models.models.TaskContext`
                    and :class:`DigestNewsInput` content.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`DigestNewsOutput`.
    """
    ctx = task_input.ctx
    inp = task_input.content
    payload = inp.model_dump(mode="json")

    # Fast path — all upstream tasks from cache; reuse existing news_stats rows.
    if inp.from_cache and inp.news_raw_id is not None:
        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(NewsStatsSQL.GET_BY_NEWS_RAW_ID, (inp.news_raw_id,))
            stats_rows = await cur.fetchall()
        if stats_rows:
            symbol: str | None = next((r["symbol"] for r in stats_rows if r["symbol"]), None)
            markdown = _build_markdown(stats_rows, symbol)
            upserted_ids = [r["id"] for r in stats_rows]
            output = DigestNewsOutput(
                upserted_ids=upserted_ids,
                markdown=markdown,
                from_cache=True,
            )
            await create_task(
                ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
                view_type="Markdown",
            )
            await complete_task(
                ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
                output_data=output.model_dump(mode="json"),
                view_type="Markdown",
            )
            return TaskOutput(ctx=ctx, content=output)

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type="Markdown",
    )
    try:
        result = await delegate_completion(
            ctx.thread_id, ctx.task_id, ctx.node_id, ctx.node_name, ctx.task_name, payload,
        )
    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            failed=True, error=str(exc),
        )
        raise
    output = DigestNewsOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)


digest_news: NodeTask[DigestNewsInput, DigestNewsOutput] = NodeTask(
    name=_TASK_NAME,
    description=(
        "Read raw articles from fin_markets.news_raw by news_raw_id, combine with "
        "pre-computed LLM summaries (do_summary) and embeddings (do_emb), upsert to "
        "fin_markets.news_stats, and render a Markdown digest of all stored rows."
    ),
    input_type=DigestNewsInput,
    output_type=DigestNewsOutput,
    task_fn=_digest_news_task,
    handler=_handler,
)

HANDLERS: dict[str, object] = {_TASK_NAME: _handler}

__all__ = ["DigestNewsInput", "DigestNewsOutput", "digest_news", "HANDLERS"]
