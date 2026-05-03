"""merge — Pydantic task-level I/O models for the merge aggregation task.

These models type the JSON stored in ``tasks.output`` (via
:func:`~backend.sse_notifications.complete_task`) and returned by
:func:`~backend.graph.agents._shared.nodes.merge_node.tasks.merge.workflow.run_merge_task`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MergeTaskInput(BaseModel):
    """Input provided to :func:`run_merge_task`.

    Attributes:
        symbol:        Ticker symbol from upstream ``query_response``.
        analysis_type: Analysis mode forwarded from ``query_response``.
        time_horizon:  Horizon forwarded from ``query_response``.
        news_articles: Raw news-article dicts from the news node.
        stats_records: Market-stats record dicts from the stats node.
    """

    symbol: str
    analysis_type: str
    time_horizon: str
    news_articles: list[dict[str, Any]] = Field(default_factory=list)
    stats_records: list[dict[str, Any]] = Field(default_factory=list)


class MergeTaskOutput(BaseModel):
    """Output produced by the merge task.

    Stored in graph state as ``merged_analysis`` and serialised to
    ``tasks.output``.

    Attributes:
        symbol:        Ticker symbol.
        analysis_type: Analysis mode.
        time_horizon:  Horizon window.
        news:          Aggregated news-article dicts.
        stats:         Aggregated market-stats record dicts.
    """

    symbol: str
    analysis_type: str
    time_horizon: str
    news: list[dict[str, Any]] = Field(default_factory=list)
    stats: list[dict[str, Any]] = Field(default_factory=list)

    def as_dict(self) -> dict:
        """Return a serialisable dict for node/task output storage."""
        return self.model_dump()


__all__ = ["MergeTaskInput", "MergeTaskOutput"]
