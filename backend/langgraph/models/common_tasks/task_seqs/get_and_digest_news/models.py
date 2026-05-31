"""Models for the get_and_digest_news task sequence."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from backend.langgraph.models.common_tasks.task_seqs.get_and_digest_news.digest_news import DigestNewsOutput
from backend.langgraph.models.common_tasks.task_seqs.get_and_digest_news.do_emb import DoEmbOutput
from backend.langgraph.models.common_tasks.task_seqs.get_and_digest_news.do_summary import DoSummaryOutput
from backend.langgraph.models.common_tasks.task_seqs.get_and_digest_news.get_news import GetNewsOutput


class GetAndDigestNewsInput(BaseModel):
    """Input for the get_and_digest_news task sequence.

    Attributes:
        symbol:     Equity ticker, e.g. ``'AAPL'``.  ``None`` for topic-only news.
        topics:     Topic keywords to narrow/augment the search.
        from_dt:    Start of the news date window (UTC).
        to_dt:      End of the news date window (UTC).
        news_limit: Max news articles passed to ``get_news``.
    """

    symbol: str | None = Field(default=None, description="Equity ticker, e.g. 'AAPL'.")
    topics: list[str] = Field(default_factory=list, description="Topic keywords to filter/augment search.")
    from_dt: datetime | None = Field(default=None, description="Start of date window (UTC).")
    to_dt: datetime | None = Field(default=None, description="End of date window (UTC).")
    news_limit: int = Field(default=20, ge=1, le=100, description="Max news articles to fetch.")


class GetAndDigestNewsOutput(BaseModel):
    """Combined output from the get_news → do_summary → do_emb → digest_news pipeline.

    Attributes:
        get_news:    Output from the ``get_news`` task (JSON view).
        do_summary:  Output from the ``do_summary`` task (url_hash → SummaryRecord).
        do_emb:      Output from the ``do_emb`` task (url_hash → embedding vector).
        digest_news: Output from the ``digest_news`` task (Markdown view + upserted IDs).
    """

    get_news: GetNewsOutput
    do_summary: DoSummaryOutput
    do_emb: DoEmbOutput
    digest_news: DigestNewsOutput


__all__ = ["GetAndDigestNewsInput", "GetAndDigestNewsOutput"]
