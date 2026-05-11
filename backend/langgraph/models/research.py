"""Content models for research_subgraph tasks.

These represent the ``input`` and ``output`` JSONB columns stored in
``fin_agents.tasks`` and ``fin_agents.nodes`` for:

* ``read_stats``    → stats_node
* ``read_news``     → news_node
* ``merge_results`` → merge_node
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "ReadStatsInput",
    "ReadStatsOutput",
    "ReadNewsInput",
    "ReadNewsOutput",
    "MergeResultsInput",
    "MergeResultsOutput",
]


# ---------------------------------------------------------------------------
# read_stats
# ---------------------------------------------------------------------------


class ReadStatsInput(BaseModel):
    """Input payload for the ``read_stats`` task and ``stats_node``."""

    symbols: list[str] = Field(default_factory=lambda: ["AAPL"])
    interval: str = Field(default="1d", description="OHLCV bar interval (e.g. '1d', '1h').")


class ReadStatsOutput(BaseModel):
    """Output payload for the ``read_stats`` task and ``stats_node``."""

    symbol: str
    interval: str
    records: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# read_news
# ---------------------------------------------------------------------------


class ReadNewsInput(BaseModel):
    """Input payload for the ``read_news`` task and ``news_node``."""

    symbols: list[str] = Field(default_factory=lambda: ["AAPL"])


class ReadNewsOutput(BaseModel):
    """Output payload for the ``read_news`` task and ``news_node``."""

    symbol: str
    articles: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# merge_results
# ---------------------------------------------------------------------------


class MergeResultsInput(BaseModel):
    """Input payload for the ``merge_results`` task and ``merge_node``."""

    stats_data: dict[str, Any] = Field(default_factory=dict)
    news_data: dict[str, Any] = Field(default_factory=dict)


class MergeResultsOutput(BaseModel):
    """Output payload for the ``merge_results`` task and ``merge_node``."""

    symbol: str
    summary: str
    stats: dict[str, Any] = Field(default_factory=dict)
    news: dict[str, Any] = Field(default_factory=dict)
