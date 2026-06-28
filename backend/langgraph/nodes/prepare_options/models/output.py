"""Output model for prepare_options node."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.langgraph.nodes.prepare_options.models.input import (
    MaturityRequest,
    PrepareOptionsRequestItem,
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
        pipeline:       Which pipeline produced this result -- ``'ohlcv'``,
                        ``'options'``, or ``'futures'``.
        symbol:         Ticker this result covers.
        maturity_label: For options / futures pipelines, the maturity-window
                        identifier (e.g. ``'one_week'`` / ``'one_year'``).
                        ``None`` for plain OHLCV.
        maturity_seconds: Width of the maturity window in seconds; ``None``
                          for plain OHLCV items.
        rows_upserted:  Number of rows written by the calculate step.
        from_cache:     Whether the raw stats were served from cache.
    """

    pipeline: str = Field(
        description="Pipeline that produced this result: 'ohlcv', 'options', or 'futures'."
    )
    symbol: str = Field(description="Ticker this result covers.")
    maturity_label: str | None = Field(
        default=None,
        description="Maturity-window identifier (e.g. 'one_year'); None for plain OHLCV items.",
    )
    maturity_seconds: int | None = Field(
        default=None,
        description="Width of the maturity window in seconds; None for plain OHLCV items.",
    )
    rows_upserted: int = Field(
        default=0, description="Rows written by the calculate step."
    )
    from_cache: bool = Field(
        default=False, description="Whether raw stats were cache-served."
    )


class PrepareOptionsOutput(BaseModel):
    """Typed output for ``prepare_options``.

    Persisted to ``fin_agents.node_executions`` for downstream nodes / rendering.

    Attributes:
        stock_symbol: Equity ticker under analysis.
        results:      Per-pipeline execution summaries.
        df_splits:    Per-symbol OHLCV df_split payloads for StackCandleStick rendering.
        requests:     Optional copy of the plan items that were actually
                      executed, useful for rendering the node's own progress view.
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
    requests: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Copy of the plan items that were executed (explicit from the "
            "caller, or synthesised from the catalogue). Used for rendering "
            "and downstream audit."
        ),
    )


class PrepareOptionsRequestsOutput(BaseModel):
    """Output from the ``prepare_options_requests`` task.

    Two production modes:

    * ``explicit_requests=True``: the caller supplied ``requests`` verbatim.
      ``requests`` is returned as-is (validated into
      :class:`PrepareOptionsRequestItem` objects) and ``maturities`` is
      synthesised from the explicit items.
    * ``explicit_requests=False`` (legacy): the task built a plan from the
      ``OPTIONS_PERIODS`` catalogue.

    Attributes:
        maturities:         One entry per maturity window in the plan.
        requests:           The same windows expressed as items ready to feed
                             directly into ``get_and_calculate_stats``.
        source_symbol:      Symbol this plan is keyed to (provenance).
        explicit_requests:  ``True`` when ``requests`` was provided verbatim
                             by the caller; ``False`` when the plan was
                             synthesised from the catalogue.
    """

    maturities: list[MaturityRequest] = Field(
        default_factory=list,
        description=(
            "One entry per maturity window in the plan; ordered by ascending "
            "seconds so short-dated pipelines are dispatched first."
        ),
    )
    requests: list[PrepareOptionsRequestItem] = Field(
        default_factory=list,
        description=(
            "Plan items ready to feed directly into get_and_calculate_stats. "
            "Each carries pipeline, period, symbol, and maturity_horizon."
        ),
    )
    source_symbol: str = Field(
        default="",
        description="Symbol this plan is keyed to (provenance only).",
    )
    explicit_requests: bool = Field(
        default=False,
        description=(
            "True when requests was provided verbatim by the caller; "
            "False when the plan was synthesised from the catalogue."
        ),
    )
