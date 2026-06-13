"""Input model for prepare_options node."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.quant.stats.constants import FUTURES_OPTIONS_PERIODS

__all__ = [
    "PrepareOptionsInput",
    "PrepareOptionsRequestsInput",
    "MaturityRequest",
]


class PrepareOptionsInput(BaseModel):
    """Typed input for ``prepare_options``.

    Attributes:
        stock_symbol:     Equity ticker under analysis, e.g. ``'AAPL'``.
        ohlcv_period:     Period used for the companion OHLCV pipeline, e.g. ``'1y'``.
        options_period:   Period label used for the options-stats pipeline, e.g. ``'1y'``.
        maturity_horizon: How far out to pull maturities for time-bounded products
                          (options, futures, bonds, repo, ...).  Accepts a
                          :class:`~backend.quant.stats.constants.FUTURES_OPTIONS_PERIODS`
                          member, one of its ``display_name`` strings
                          (``'next'``, ``'one week'``, ``'one month'``,
                          ``'one quarter'``, ``'half year'``, ``'one year'``),
                          or a raw number of seconds.  ``None`` defaults to
                          ``FUTURES_OPTIONS_PERIODS.ONE_YEAR``.
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
            "How far out to pull maturities for time-bounded products "
            "(options, futures, bonds, repo, ...). Accepts a "
            "FUTURES_OPTIONS_PERIODS member, its display_name string, "
            "or a raw number of seconds. None → ONE_YEAR."
        ),
    )


class MaturityRequest(BaseModel):
    """A single proposed maturity window for stats pipelines.

    Attributes:
        label:        Stable identifier for the window, e.g. ``'one_week'``.
        display_name: Human-readable label, e.g. ``'one week'``.
        seconds:      Window width in seconds (matches
                      ``FUTURES_OPTIONS_PERIODS.<label>.seconds``).
        pipeline:     Target pipeline for this maturity, e.g. ``'options'``.
    """

    label: str = Field(description="Stable identifier, e.g. 'one_week'.")
    display_name: str = Field(description="Human-readable label, e.g. 'one week'.")
    seconds: int = Field(description="Window width in seconds.")
    pipeline: str = Field(
        default="options",
        description="Target pipeline for this maturity, e.g. 'options'.",
    )


class PrepareOptionsRequestsInput(BaseModel):
    """Input for the ``prepare_options_requests`` task.

    This task returns the full catalogue of maturity windows available.
    ``maturity_horizon`` no longer lives here -- the hosting node owns it
    and decides which of the returned items to actually run.

    Attributes:
        stock_symbol: Equity ticker under analysis (provenance only).
        include_next: When ``True``, the ``NEXT`` (0s) window is always
                      included in the output list even though it is a
                      degenerate short-dated window.
    """

    stock_symbol: str = Field(
        default="",
        description="Equity ticker under analysis; used for provenance only.",
    )
    include_next: bool = Field(
        default=True,
        description="Always include the 'NEXT' (0s) maturity window.",
    )
