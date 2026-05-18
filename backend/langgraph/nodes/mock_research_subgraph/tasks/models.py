"""Task-level content models for the research_subgraph child nodes.

Each child node (stats_node, news_node, merge_node) has exactly one task.
The node's input and output are the same Pydantic models as the task's
input and output — there is no extra wrapping layer.

Input chaining
--------------
``ReadStatsInput`` and ``ReadNewsInput`` are constructed by the subgraph's
``orchestrate`` from the ``ResearchSubgraphInput.symbols`` field.

``MergeInput`` is constructed from the outputs of ``read_stats`` and
``read_news`` — task output chaining within the same subgraph.

``MergeOutput`` is the final research summary consumed by ``conclusion_node``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "ReadStatsInput",
    "ReadStatsOutput",
    "ReadNewsInput",
    "ReadNewsOutput",
    "MergeInput",
    "MergeOutput",
]


# ---------------------------------------------------------------------------
# read_stats
# ---------------------------------------------------------------------------


class ReadStatsInput(BaseModel):
    """Input for the read_stats task / stats_node.

    Attributes:
        symbols: Equity tickers to fetch OHLCV data for.
        interval: Bar interval (e.g. ``"1d"``, ``"1h"``).
    """

    symbols: list[str] = Field(default_factory=lambda: ["AAPL"])
    interval: str = Field(default="1d", description="OHLCV bar interval.")


class ReadStatsOutput(BaseModel):
    """Output from the read_stats task / stats_node.

    Attributes:
        symbol: The primary ticker that was fetched.
        interval: The bar interval used.
        df_split: Pandas ``orient="split"`` dict:
            ``{"index": [timestamp_str, ...], "columns": ["open", "high", ...], "data": [[...], ...]}``.
            Reconstructed as ``pd.DataFrame(**df_split, index=pd.DatetimeIndex(df_split["index"]))``.
        stats_views: Ordered list of view types the DataViewer should offer for this output
            (e.g. ``["DataFrame", "CandleStick"]``).  Embedded in the output so both
            task and node output views can render the dropdown without separate metadata.
    """

    symbol: str
    interval: str
    df_split: dict[str, Any] = Field(default_factory=dict)
    stats_views: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# read_news
# ---------------------------------------------------------------------------


class ReadNewsInput(BaseModel):
    """Input for the read_news task / news_node.

    Attributes:
        symbols: Equity tickers to fetch news articles for.
    """

    symbols: list[str] = Field(default_factory=lambda: ["AAPL"])


class ReadNewsOutput(BaseModel):
    """Output from the read_news task / news_node.

    Attributes:
        symbol: The primary ticker that was fetched.
        articles: List of news article dicts.
    """

    symbol: str
    articles: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# merge_results
# ---------------------------------------------------------------------------


class MergeInput(BaseModel):
    """Input for the merge_results task / merge_node.

    Constructed from the chained outputs of read_stats and read_news within
    the same subgraph orchestration step.

    Attributes:
        stats_data: Serialised ``ReadStatsOutput`` dict.
        news_data: Serialised ``ReadNewsOutput`` dict.
    """

    stats_data: dict[str, Any] = Field(default_factory=dict)
    news_data: dict[str, Any] = Field(default_factory=dict)


class MergeOutput(BaseModel):
    """Output from the merge_results task / merge_node.

    Attributes:
        symbol: The primary ticker in the merged summary.
        summary: Human-readable research summary string.
        stats: Passed-through stats data dict.
        news: Passed-through news data dict.
    """

    symbol: str
    summary: str = Field(default="")
    stats: dict[str, Any] = Field(default_factory=dict)
    news: dict[str, Any] = Field(default_factory=dict)
