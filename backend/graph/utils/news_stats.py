"""news_stats transformer: converts raw NewsResult articles into enriched news_stats rows.

Pipeline per article batch:
  1. Call the LLM enrichment prompt to generate ai_summary, sentiment, region,
     sector, impact category, and free-form topics for every article in one batch call.
  2. Embed the LLM-generated ai_summary via the configured embedding provider.
  3. Normalise the embedding vector to exactly 768 dimensions (pad or truncate)
     and L2-normalise it so cosine similarity works without pgvector.
  4. Fall back to article.sentiment_score → sentiment_level mapping when the LLM
     does not return a sentiment (or when enrichment fails entirely).
  5. Upsert the fully-enriched rows into ``fin_markets.news_stats``.

The transformer is called only on fresh fetches (``news_raw_id is not None``).
Cache hits skip transformation because articles were already stored on the original fetch.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from backend.db import raw_conn
from backend.db.postgres.queries.fin_markets_news import NewsStatsSQL
from backend.graph.prompts.news_enrichment import build_news_enrichment_prompt
from backend.llm.embeddings import get_embedder
from backend.resource_api.news_api.models import NewsArticle, NewsResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structured enrichment output model
# ---------------------------------------------------------------------------

class ArticleEnrichment(BaseModel):
    """LLM-classified metadata for a single news article."""

    ai_summary: Optional[str] = Field(None, description="2-3 sentence AI-generated summary")
    sentiment: Optional[str] = Field(None, description="9-point sentiment_level enum value")
    region: Optional[str] = Field(None, description="fin_markets.regions code, e.g. 'us', 'cn'")
    sector: Optional[str] = Field(None, description="fin_markets.news_sector value")
    topic_level1: Optional[str] = Field(None, description="Impact domain, e.g. 'Corporate'")
    topic_level2: Optional[str] = Field(None, description="Impact category, e.g. 'Financial Performance'")
    impact_category: Optional[str] = Field(None, description="Specific event code, e.g. 'earnings_beat'")
    topics: list[str] = Field(default_factory=list, description="Free-form tags")

# ---------------------------------------------------------------------------
# Sentiment mapping
# ---------------------------------------------------------------------------

_SENTIMENT_THRESHOLDS: list[tuple[float, str]] = [
    (0.75,  "strongly_bullish"),
    (0.50,  "bullish"),
    (0.25,  "mildly_bullish"),
    (0.05,  "slightly_bullish"),
    (-0.05, "neutral"),
    (-0.25, "slightly_bearish"),
    (-0.50, "mildly_bearish"),
    (-0.75, "bearish"),
]


def _score_to_sentiment_level(score: Optional[float]) -> Optional[str]:
    """Map a normalised sentiment score in [-1, 1] to the 9-point enum.

    Args:
        score: Normalised sentiment score, or ``None`` if unavailable.

    Returns:
        One of the ``fin_markets.sentiment_level`` enum values, or ``None``.
    """
    if score is None:
        return None
    for threshold, level in _SENTIMENT_THRESHOLDS:
        if score >= threshold:
            return level
    return "strongly_bearish"


def _url_hash(article: NewsArticle) -> str:
    """Compute a stable sha256 hash for deduplication.

    Uses the article URL when present; falls back to ``title + source_name``.

    Args:
        article: The news article to hash.

    Returns:
        Hex digest string (64 chars).
    """
    key = article.url or f"{article.title}|{article.source_name}"
    return hashlib.sha256(key.encode()).hexdigest()


_EMBEDDING_DIM = 768


def _normalize_embedding(embedding: list[float], target_dim: int = _EMBEDDING_DIM) -> list[float]:
    """Pad or truncate an embedding to ``target_dim`` dims, then L2-normalise.

    Ensures every stored vector has exactly 768 dimensions so that cosine
    similarity works correctly without pgvector's vector type.

    Args:
        embedding:  Raw embedding vector from the embedding provider.
        target_dim: Target dimensionality (default: 768).

    Returns:
        L2-normalised float list of length ``target_dim``, or an empty list
        when the input is empty (embedding unavailable).
    """
    if not embedding:
        return []
    # Pad with zeros or truncate
    if len(embedding) < target_dim:
        embedding = embedding + [0.0] * (target_dim - len(embedding))
    elif len(embedding) > target_dim:
        embedding = embedding[:target_dim]
    # L2 normalise
    norm = sum(x * x for x in embedding) ** 0.5
    if norm > 0.0:
        embedding = [x / norm for x in embedding]
    return embedding


# ---------------------------------------------------------------------------
# LLM enrichment: region / sector / impact / topics
# ---------------------------------------------------------------------------

async def _enrich_articles_batch(
    articles: list[NewsArticle],
    thread_id: Optional[str] = None,
    task_id: Optional[int] = None,
    task_key: str = "market_data_collector.web_search",
) -> list[ArticleEnrichment]:
    """Classify a batch of articles using the news-enrichment LLM prompt.

    Calls the active LLM with a prompt that lists all valid region codes,
    sectors, impact levels, and impact categories so the model can pick
    the most appropriate value for each article.

    Args:
        articles:   The articles to classify.
        thread_id:  LangGraph thread id for streaming token notifications.
        task_id:    Running task id to emit token events under.
        task_key:   Full dot-separated task key for token notification payloads.

    Returns:
        A list of :class:`ArticleEnrichment` objects in the same order as
        ``articles``.  Falls back to empty :class:`ArticleEnrichment` for
        each article on any error so the rest of the pipeline is unaffected.
    """
    if not articles:
        return []

    fallback = [ArticleEnrichment() for _ in articles]

    try:
        from langchain_core.output_parsers import StrOutputParser  # noqa: PLC0415

        from backend.llm import get_llm  # noqa: PLC0415
        from backend.sse_notifications import stream_text_task  # noqa: PLC0415

        llm = get_llm(temperature=0.0)
        prompt = build_news_enrichment_prompt()
        chain = prompt | llm | StrOutputParser()

        articles_json = json.dumps(
            [{"title": a.title, "summary": a.summary or ""} for a in articles],
            ensure_ascii=False,
        )
        if thread_id and task_id:
            raw_output: str = await stream_text_task(
                thread_id, task_id, task_key,
                chain.astream({"articles_json": articles_json}),
            )
        else:
            raw_output = await chain.ainvoke({"articles_json": articles_json})

        # Strip <think>...</think> reasoning blocks and markdown fences if present
        cleaned = re.sub(r"<think>.*?</think>", "", raw_output, flags=re.DOTALL).strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        parsed = json.loads(cleaned)
        if not isinstance(parsed, list):
            raise ValueError("LLM enrichment output is not a JSON array")

        result: list[ArticleEnrichment] = []
        for i, item in enumerate(parsed):
            if i >= len(articles):
                break
            try:
                result.append(ArticleEnrichment.model_validate(item))
            except Exception:
                result.append(ArticleEnrichment())

        # Pad if LLM returned fewer items than expected
        while len(result) < len(articles):
            result.append(ArticleEnrichment())
        return result

    except Exception as exc:
        logger.warning(
            "[news_stats] LLM enrichment failed (%d articles): %s — proceeding without enrichment",
            len(articles),
            exc,
        )
        return fallback


def _parse_published_at(raw: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 datetime string into a timezone-aware datetime.

    Args:
        raw: ISO-8601 string or ``None``.

    Returns:
        Aware ``datetime`` or ``None``.
    """
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Public transformer
# ---------------------------------------------------------------------------

async def transform_news_to_stats(
    news_raw_id: int,
    result: NewsResult,
    symbol: Optional[str] = None,
    thread_id: Optional[str] = None,
    task_id: Optional[int] = None,
    node_name: str = "market_data_collector",
    task_key: str = "market_data_collector.web_search",
) -> tuple[int, list[str]]:
    """Transform articles from a ``NewsResult`` into ``fin_markets.news_stats`` rows.

    Pipeline:
    - Calls the LLM enrichment prompt to generate ai_summary, sentiment,
      region, sector, impact category, and topics for every article in one batch.
    - Embeds the LLM-generated ai_summary (falls back to title when LLM fails).
    - Normalises the embedding to exactly 768 dimensions and L2-normalises it.
    - Falls back to api-provided sentiment_score mapping when the LLM omits sentiment.
    - Upserts the fully-enriched rows into ``fin_markets.news_stats``.

    Args:
        news_raw_id: FK to the ``fin_markets.news_raw`` row that produced this result.
        result:      Normalised ``NewsResult`` containing the articles to transform.
        symbol:      Primary ticker associated with these articles (may be ``None``
                     for topic/global news).
        thread_id:   LangGraph thread UUID for streaming token notifications.
        task_id:     Running task id to emit token events under.
        node_name:   Retained for backward compatibility; derived from ``task_key``
                     when not explicitly provided.  Unused internally.
        task_key:    Full dot-separated task key for notification payloads.

    Returns:
        Tuple of ``(upserted_count, ai_summaries)`` where ``ai_summaries`` is a
        list of the LLM-generated (or fallback) summary strings for each article,
        in the same order as ``result.articles``.
    """
    import asyncio  # noqa: PLC0415 — local import keeps module-level imports minimal

    articles = result.articles
    if not articles:
        return 0, []

    # -- LLM enrichment (generates ai_summary + metadata) -------------------
    enrichments = await _enrich_articles_batch(articles, thread_id=thread_id, task_id=task_id, task_key=task_key)

    # Resolve final ai_summary texts: prefer LLM-generated, fall back to article
    summary_texts = [
        (enrich.ai_summary or a.summary or a.title)
        for a, enrich in zip(articles, enrichments)
    ]

    # -- Embed the LLM-generated summaries -----------------------------------
    embeddings: list[list[float]] = []
    try:
        embedder = get_embedder()
        embeddings = await asyncio.to_thread(embedder.embed_documents, summary_texts)  # type: ignore[attr-defined]
    except Exception as exc:
        logger.warning(
            "[news_stats] embedding failed (news_raw_id=%s): %s — proceeding without embeddings",
            news_raw_id,
            exc,
        )
        embeddings = [[] for _ in articles]

    # -- Build upsert rows ---------------------------------------------------
    rows: list[tuple] = []
    sym = (symbol or "").upper() or None

    for article, summary_text, embedding, enrich in zip(articles, summary_texts, embeddings, enrichments):
        # Prefer LLM-derived sentiment; fall back to API sentiment_score mapping
        sentiment: Optional[str] = enrich.sentiment or _score_to_sentiment_level(article.sentiment_score)
        normalised_embedding = _normalize_embedding(embedding)
        embedding_val: Optional[list[float]] = normalised_embedding if normalised_embedding else None
        published_at = _parse_published_at(article.published_at)

        rows.append((
            news_raw_id,             # news_raw_id
            result.source,           # source
            sym,                     # symbol (nullable)
            _url_hash(article),      # url_hash
            article.title,           # title
            article.source_name,     # source_name
            published_at,            # published_at
            summary_text,            # ai_summary
            embedding_val,           # summary_embedding FLOAT[]
            sentiment,               # sentiment_level ::fin_markets.sentiment_level
            enrich.sector,           # sector ::fin_markets.news_sector
            enrich.topic_level1,     # topic_level1
            enrich.topic_level2,     # topic_level2
            enrich.impact_category,  # impact_category (FK to news_impact_categories)
            enrich.topics or [],     # topics text[]
            enrich.region,           # region (FK to fin_markets.regions)
        ))

    # -- Batch upsert --------------------------------------------------------
    async with raw_conn() as conn:
        async with conn.cursor() as cur:
            await cur.executemany(NewsStatsSQL.UPSERT, rows)

    logger.info(
        "[news_stats] upserted %d article rows (news_raw_id=%s, symbol=%s)",
        len(rows), news_raw_id, sym,
    )
    return len(rows), summary_texts
