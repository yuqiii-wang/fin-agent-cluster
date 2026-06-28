"""Input model for prepare_options node."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.quant.stats.constants import OPTIONS_PERIODS

__all__ = [
    "PrepareOptionsInput",
    "PrepareOptionsRequestsInput",
    "PrepareOptionsRequestItem",
    "MaturityRequest",
]


class PrepareOptionsInput(BaseModel):
    """Typed input for ``prepare_options``.

    Attributes:
        stock_symbol:     Equity ticker under analysis, e.g. ``'AAPL'``.
        ohlcv_period:     Period used for the companion OHLCV pipeline, e.g. ``'1y'``.
        options_period:   Period label used for the options-stats pipeline, e.g. ``'1y'``.
        maturity_horizon: How far out to pull maturities when the node synthesises
                          a plan from scratch.  Accepts a
                          :class:`~backend.quant.stats.constants.OPTIONS_PERIODS`
                          member, its ``display_name`` string, or a raw number of seconds.
                          ``None`` defaults to ``OPTIONS_PERIODS.ONE_YEAR``.
        requests:         Optional list of explicit ``get_and_calculate_stats``
                          plan items.  When provided, this list is used verbatim
                          by ``prepare_options_requests`` -- the caller retains
                          full control of which ``pipeline`` /
                          ``maturity_horizon`` / period to run.  Each item mirrors
                          :class:`PrepareOptionsRequestItem` shape.
    """

    stock_symbol: str = Field(
        default="",
        description="Equity ticker under analysis, resolved from query_node output.",
    )
    ohlcv_period: str = Field(
        default="1y",
        description="Stats period used for the companion OHLCV pipeline.",
    )
    options_period: str = Field(
        default="1y",
        description="Stats period label used for the options-stats pipeline.",
    )
    maturity_horizon: Any = Field(
        default=None,
        description=(
            "How far out to pull maturities when the node synthesises a plan "
            "from scratch. Accepts a OPTIONS_PERIODS member, its "
            "display_name string, or a raw number of seconds. None → ONE_YEAR."
        ),
    )
    requests: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Optional explicit list of get_and_calculate_stats plan items. "
            "When provided, it is forwarded verbatim to prepare_options_requests "
            "and the caller retains full control of pipeline / period / "
            "maturity_label / maturity_horizon / maturity_seconds."
        ),
    )


class MaturityRequest(BaseModel):
    """A single proposed maturity window for stats pipelines.

    Attributes:
        label:        Stable identifier for the window, e.g. ``'one_week'``.
        display_name: Human-readable label, e.g. ``'one week'``.
        seconds:      Window width in seconds.
        pipeline:     Target pipeline for this maturity, e.g. ``'options'``.
    """

    label: str = Field(description="Stable identifier, e.g. 'one_week'.")
    display_name: str = Field(description="Human-readable label, e.g. 'one week'.")
    seconds: int = Field(description="Window width in seconds.")
    pipeline: str = Field(
        default="options",
        description="Target pipeline for this maturity, e.g. 'options'.",
    )


class PrepareOptionsRequestItem(BaseModel):
    """A single ``get_and_calculate_stats`` request proposed by prepare_options_requests.

    Directly consumable by
    :class:`~backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.GetAndCalculateStatsInput`.

    Attributes:
        period:           Aggregation period, e.g. ``'1y'``.
        symbol:           Ticker to fetch stats for.
        pipeline:         Target pipeline, e.g. ``'options'``, ``'ohlcv'``,
                          or ``'futures'``.
        maturity_label:   Stable identifier for the maturity window
                          (e.g. ``'one_year'``); ``None`` for plain OHLCV items.
        maturity_horizon: ``OPTIONS_PERIODS`` seconds forwarded to the
                          fetch pipeline when ``pipeline`` is time-bounded.
        maturity_seconds: Width of the maturity window in seconds; used by the
                          hosting node for horizon-filtering and downstream
                          result grouping.
    """

    period: str = Field(description="Aggregation period, e.g. '1y'.")
    symbol: str = Field(description="Ticker to fetch stats for.")
    pipeline: str = Field(
        default="options",
        description="Target pipeline: 'options', 'ohlcv', or 'futures'.",
    )
    maturity_label: str | None = Field(
        default=None,
        description=(
            "Stable identifier (e.g. 'one_year') for provenance / grouping; "
            "None for plain OHLCV items."
        ),
    )
    maturity_horizon: Any = Field(
        default=None,
        description=(
            "OPTIONS_PERIODS seconds forwarded to the fetch pipeline "
            "for time-bounded products (options / futures / bonds / repo ...)."
        ),
    )
    maturity_seconds: int | None = Field(
        default=None,
        description="Width of the maturity window in seconds; None for plain OHLCV items.",
    )


class PrepareOptionsRequestsInput(BaseModel):
    """Input for the ``prepare_options_requests`` task.

    Two input shapes are supported:

    * **Explicit plan (preferred):** ``{"requests": [...]}`` -- each item
      describes one ``get_and_calculate_stats`` invocation and is used
      verbatim (its ``pipeline`` / ``period`` / ``symbol`` /
      ``maturity_horizon`` / ``maturity_seconds`` / ``maturity_label`` are
      forwarded unchanged).  The caller's ``stock_symbol`` / ``period`` /
      ``maturity_horizon`` are only used for provenance and defaulting.
    * **Synthesised plan:** when ``requests`` is omitted, the task builds a
      plan from ``stock_symbol`` + the full ``OPTIONS_PERIODS``
      catalogue (``include_next`` controls inclusion of the degenerate
      ``NEXT`` window).

    Attributes:
        stock_symbol:   Symbol used for provenance and as the default for
                        synthesised plans.
        period:         Default period used when synthesising a plan.
        include_next:   Whether to include the ``NEXT`` (0s) window when
                        synthesising a plan from the catalogue.
        requests:       Optional explicit list of ``get_and_calculate_stats``
                        plan items (see :class:`PrepareOptionsRequestItem`).
                        When provided, takes precedence over catalogue-based
                        synthesis.
    """

    stock_symbol: str = Field(
        default="",
        description=(
            "Symbol used for provenance and as the default when synthesising a plan."
        ),
    )
    period: str = Field(
        default="1y",
        description="Default period used when synthesising a plan.",
    )
    include_next: bool = Field(
        default=True,
        description="Whether to include the 'NEXT' (0s) window in catalogue-based plans.",
    )
    requests: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Optional explicit list of get_and_calculate_stats plan items "
            "(shape matches PrepareOptionsRequestItem). When provided, takes "
            "precedence over catalogue-based synthesis."
        ),
    )
