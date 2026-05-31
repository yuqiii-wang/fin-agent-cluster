"""Output model for prepare_news node."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["PrepareNewsOutput"]


class PrepareNewsOutput(BaseModel):
    """Typed output for ``prepare_news``.

    Persisted to ``fin_agents.node_executions`` for downstream nodes.

    Attributes:
        symbol:              Equity ticker processed (or ``None`` for topic-only news).
        input_raw_id:         PK of the ``input_raw`` cache row inserted/reused.
        upserted_ids:        List of ``news_stats.id`` rows written by ``digest_news``.
        news_articles_count: Number of raw news articles fetched.
        from_cache:          Whether ``get_news`` returned a cached result.
    """

    symbol: str | None = Field(default=None, description="Equity ticker processed.")
    input_raw_id: int | None = Field(default=None, description="PK of the input_raw cache row.")
    upserted_ids: list[int] = Field(
        default_factory=list,
        description="IDs of news_stats rows upserted by digest_news.",
    )
    news_articles_count: int = Field(default=0, description="Number of raw news articles fetched.")
    from_cache: bool = Field(default=False, description="Whether get_news used a cached result.")
    markdown: str = Field(default="", description="Markdown digest rendered by digest_news.")
