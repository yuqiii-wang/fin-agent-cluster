"""Output model for prepare_options node."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.langgraph.nodes.prepare_options.models.input import (
    MaturityRequest,
)

__all__ = [
    "PrepareOptionsOutput",
    "OptionsStatResult",
    "PrepareOptionsRequestsOutput",
    "PrepareOptionsRequestItem",
]


class OptionsStatResult(BaseModel):
    """Stats result for a single instrument / pipeline executed by prepare_options.

    Attributes:
        pipeline:       Which pipeline produced this result -- ``'ohlcv'`` or ``'options'``.
        symbol:         Ticker this result covers.
        maturity_label: For options pipelines, the maturity-window identifier
                        (e.g. ``'one_week'``).  ``None`` for OHLCV.
        rows_upserted:  Number of rows written by the calculate step.
        from_cache:     Whether the raw stats were served from cache.
    """

    pipeline: str = Field(description="Pipeline that produced this result: 'ohlcv' or 'options'.")
    symbol: str = Field(description="Ticker this result covers.")
    maturity_label: str | None = Field(
        default=None,
        description="For options, the maturity-window identifier such as 'one_week'; None for OHLCV.",
    )
    rows_upserted: int = Field(default=0, description="Rows written by the calculate step.")
    from_cache: bool = Field(default=False, description="Whether raw stats were cache-served.")


class PrepareOptionsOutput(BaseModel):
    """Typed output for ``prepare_options``.

    Persisted to ``fin_agents.node_executions`` for downstream nodes / rendering.

    Attributes:
        stock_symbol:  Equity ticker under analysis.
        results:       Per-pipeline execution summaries.
        df_splits:     Per-symbol OHLCV df_split payloads for StackCandleStick rendering.
    """

    stock_symbol: str = Field(default="", description="Equity ticker under analysis.")
    results: list[OptionsStatResult] = Field(
        default_factory=list,
        description="Per-pipeline execution summaries from get_and_calculate_stats.",
    )
    df_splits: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Per-symbol OHLCV df_split payloads for StackCandleStick rendering.",
    )


class PrepareOptionsRequestItem(BaseModel):
    """A single ``get_and_calculate_stats`` request proposed by prepare_options_requests.

    These items are **directly consumable** by
    :class:`~backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.GetAndCalculateStatsInput`,
    so the hosting node can fan them out without re-interpreting the plan.

    Attributes:
        symbol:           Ticker to fetch stats for (mirrors ``GetAndCalculateStatsInput.symbol``).
        period:           Aggregation period (mirrors
                          ``GetAndCalculateStatsInput.period``).
        pipeline:         Target pipeline, e.g. ``'options'`` or ``'ohlcv'``.
        maturity_horizon: Maturity horizon forwarded verbatim to ``get_and_calculate_stats``
                          when ``pipeline='options'``.  ``None`` for plain OHLCV pipelines.
        maturity_label:   Stable identifier for the maturity window (e.g. ``'one_week'``);
                          used for provenance and downstream result grouping.
        maturity_seconds: Width of the maturity window in seconds.
    """

    symbol: str = Field(description="Ticker to fetch stats for.")
    period: str = Field(description="Aggregation period, e.g. '1y'.")
    pipeline: str = Field(default="options", description="Target pipeline: 'options' or 'ohlcv'.")
    maturity_horizon: Any = Field(
        default=None,
        description=(
            "Maturity horizon forwarded to get_and_calculate_stats for the 'options' pipeline. "
            "Stored as the raw seconds int so the provider can snap/interpret it directly."
        ),
    )
    maturity_label: str | None = Field(
        default=None,
        description="Stable identifier (e.g. 'one_week') for provenance / result grouping; None for plain OHLCV items.",
    )
    maturity_seconds: int | None = Field(
        default=None,
        description="Width of the maturity window in seconds; None for plain OHLCV items.",
    )


class PrepareOptionsRequestsOutput(BaseModel):
    """Output from the ``prepare_options_requests`` task.

    Describes which maturity windows the node should run a full
    ``get_and_calculate_stats`` pipeline for.

    ``prepare_options_requests`` no longer accepts ``maturity_horizon`` in
    its input -- it always emits the full catalogue of available windows
    (ordered by ascending seconds).  The hosting node decides which ones to
    actually run based on its own ``maturity_horizon``.

    Attributes:
        maturities:     One entry per maturity window known to the system;
                        ordered by ascending ``seconds`` so the node can
                        dispatch short-dated pipelines first.
        requests:       The same windows expressed as items ready to feed
                        directly into ``get_and_calculate_stats`` -- each
                        carries ``symbol``, ``period``, ``pipeline='options'``
                        and a ``maturity_horizon`` equal to the window's
                        ``seconds``.  The caller overrides ``period`` /
                        ``symbol`` as needed before launching.
        source_symbol:  Equity ticker this plan covers (provenance only).
    """

    maturities: list[MaturityRequest] = Field(
        default_factory=list,
        description=(
            "One entry per maturity window known to the system; ordered by "
            "ascending seconds so short-dated pipelines are dispatched first."
        ),
    )
    requests: list[PrepareOptionsRequestItem] = Field(
        default_factory=list,
        description=(
            "The same maturity windows expressed as items ready to feed "
            "directly into get_and_calculate_stats. Each carries pipeline='options' "
            "and maturity_horizon equal to the window seconds."
        ),
    )
    source_symbol: str = Field(
        default="",
        description="Equity ticker this plan covers (provenance only).",
    )
