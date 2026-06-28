"""calculate_futures_stats -- compute OHLCV technical indicators for futures.

Futures contracts emit OHLCV-shaped bars identical to equities / indexes
from a pandas perspective, so we reuse the :mod:`backend.quant.stats`
indicator pipeline (SMA, EMA, MACD, RSI, Bollinger, ATR, ADX, Stochastic,
Williams %R, CCI, MFI, ROC, VWAP, OBV, A/D) implemented by
:func:`~backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculate_ohlcv_stats.calculate_ohlcv_stats_handler`.

The difference vs the shared OHLCV handler:

* Record id / source prefixes ``'yf-futures'`` / ``'fmp-futures'`` are
  recognised so downstream rendering (StackCandleStick, futures-view
  panels) can distinguish futures bars from plain OHLCV.
* The handler accepts a ``maturity_horizon`` that is stored on the
  output record so the caller can associate bars with a specific
  expiration window (e.g. "near-month" / "one-quarter").

Public exports
--------------
``CalculateFuturesStatsInput``    -- Pydantic input model.
``CalculateFuturesStatsOutput``   -- Pydantic output model.
``calculate_futures_stats_handler`` -- async Celery handler.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculate_ohlcv_stats import (
    CalculateOhlcvStatsInput,
    CalculateOhlcvStatsOutput,
    calculate_ohlcv_stats_handler,
)
from backend.quant.stats.constants import OPTIONS_PERIODS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class CalculateFuturesStatsInput(BaseModel):
    """Input for the futures-stats handler.

    Attributes:
        stats_record:     OHLCV stats record for a futures ticker (``CL=F``
                          / ``ES=F`` / ``GC=F`` / ``BTC-USD`` / ...).
        from_cache:       When ``True``, return existing row count without
                          recomputing indicators (mirrors the OHLCV handler).
        pipeline:         Must be ``'futures'``; used as a safety tag.
        maturity_horizon: Optional maturity-horizon value forwarded by the
                          hosting node.  Interpreted the same way as
                          ``GetAndCalculateStatsInput.maturity_horizon``.
    """

    stats_record: Any = Field(description="OHLCV stats record for a futures ticker.")
    from_cache: bool = Field(
        default=False,
        description="When True, return existing row count without recomputing indicators.",
    )
    pipeline: str = Field(
        default="futures",
        description="Pipeline label; must be 'futures'.",
    )
    maturity_horizon: Any = Field(
        default=None,
        description=(
            "Optional maturity horizon forwarded by the hosting node. "
            "Interpreted as a OPTIONS_PERIODS member, display_name, "
            "or raw seconds. Mirrors GetAndCalculateStatsInput.maturity_horizon."
        ),
    )


class CalculateFuturesStatsOutput(CalculateOhlcvStatsOutput):
    """Futures-specific extension of the OHLCV stats output.

    Attributes:
        maturity_label:   Short label for the maturity window (e.g.
                          ``'one_month'``).  ``None`` when no horizon was
                          provided by the caller.
        maturity_seconds: Raw seconds width of the maturity window.
        pipeline:         Fixed to ``'futures'`` so downstream consumers can
                          distinguish futures bars from plain OHLCV bars.
    """

    maturity_label: str | None = Field(
        default=None,
        description="Short maturity-window label, e.g. 'one_month'; None when no horizon provided.",
    )
    maturity_seconds: int | None = Field(
        default=None,
        description="Raw seconds width of the maturity window; None when no horizon provided.",
    )
    pipeline: str = Field(
        default="futures",
        description="Fixed to 'futures' so downstream consumers can distinguish from plain OHLCV bars.",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _horizon_label_and_seconds(value: object) -> tuple[str | None, int | None]:
    """Normalise a ``maturity_horizon`` to ``(label, seconds)``.

    Same rules as :func:`get_stats_utils.common._horizon_label_and_seconds`.
    ``None`` input → ``(None, None)``.
    """

    if value is None:
        return None, None

    if isinstance(value, OPTIONS_PERIODS):
        return value.name.lower(), int(value.seconds)

    if isinstance(value, str):
        key = value.strip().lower().replace("_", " ")
        if not key:
            return None, None
        for member in OPTIONS_PERIODS:
            if member.display_name.lower() == key or member.name.lower() == key:
                return member.name.lower(), int(member.seconds)
        try:
            seconds = int(float(key))
        except ValueError:
            return None, None
        return _snap_seconds_to_label(seconds)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _snap_seconds_to_label(int(value))

    if isinstance(value, (tuple, list)) and len(value) == 2:
        try:
            seconds = int(value[1])
        except (TypeError, ValueError):
            return None, None
        return _snap_seconds_to_label(seconds)

    return None, None


def _snap_seconds_to_label(seconds: int) -> tuple[str, int]:
    """Snap raw seconds to the nearest-fitting enum member."""

    ordered = sorted(OPTIONS_PERIODS, key=lambda m: m.seconds)
    chosen_label = f"{seconds}s"
    chosen_seconds = seconds
    for member in ordered:
        if member.seconds <= seconds:
            chosen_label = member.name.lower()
            chosen_seconds = int(member.seconds)
        else:
            break
    return chosen_label, chosen_seconds


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


async def calculate_futures_stats_handler(payload: dict) -> dict:
    """Compute technical indicators for a futures OHLCV record.

    Delegates the heavy lifting (indicators + DB upsert) to
    :func:`calculate_ohlcv_stats_handler` and then stamps the output with
    futures-specific metadata (``maturity_label``, ``maturity_seconds``,
    ``pipeline='futures'``) so consumers can distinguish futures bars
    from plain OHLCV bars.

    Args:
        payload: Serialised :class:`CalculateFuturesStatsInput` dict.

    Returns:
        Serialised :class:`CalculateFuturesStatsOutput` dict.
    """

    inp = CalculateFuturesStatsInput.model_validate(payload)
    ohlcv_payload = CalculateOhlcvStatsInput(
        stats_record=inp.stats_record,
        from_cache=inp.from_cache,
        pipeline="ohlcv",
    ).model_dump(mode="json")

    ohlcv_result = await calculate_ohlcv_stats_handler(ohlcv_payload)
    ohlcv_output = CalculateOhlcvStatsOutput.model_validate(ohlcv_result)

    maturity_label, maturity_seconds = _horizon_label_and_seconds(inp.maturity_horizon)

    output = CalculateFuturesStatsOutput(
        # Base fields (CalculateOhlcvStatsOutput inherits from
        # CalculateStatsBaseOutput):
        rows_upserted=ohlcv_output.rows_upserted,
        symbol=ohlcv_output.symbol,
        source=ohlcv_output.source,
        stats_views=ohlcv_output.stats_views,
        granularity=ohlcv_output.granularity,
        df_split=ohlcv_output.df_split,
        # Futures-specific fields:
        maturity_label=maturity_label,
        maturity_seconds=maturity_seconds,
        pipeline="futures",
    )
    return output.model_dump(mode="json")


__all__ = [
    "CalculateFuturesStatsInput",
    "CalculateFuturesStatsOutput",
    "calculate_futures_stats_handler",
]
