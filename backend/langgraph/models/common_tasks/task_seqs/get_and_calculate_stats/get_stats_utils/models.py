"""models -- shared Pydantic models for the get_stats task family.

Declares the input / output models used by all product-specific handlers
(``get_ohlcv_stats``, ``get_options_stats``, ``get_futures_stats``,
``get_fundamental_stats``).  The same models are also re-exported from the
top-level :mod:`backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats`
for backwards compatibility.

Public exports
--------------
``GetStatsInput``  -- Pydantic input model (symbol, period, text/json injection,
                      maturity_horizon, provenance).
``GetStatsOutput`` -- Pydantic output model (StatsRecord, from_cache, pipeline).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.quant.stats import STATS_DATA_TYPE
from backend.resources.stats.models import StatsRecord


class GetStatsInput(BaseModel):
    """Input for the get_stats task.

    Attributes:
        symbol:           Equity/instrument ticker, e.g. ``'AAPL'``.
        period:           Aggregation period, e.g. ``'1d'``, ``'1mo'``.
        text_content:     Free-form text to inject instead of fetching; produces
                          a non-OHLCV stub record.
        json_input:       Structured OHLCV matrix or full ``StatsRecord`` dict
                          handed down from a previous task.
        maturity_horizon: Optional horizon for time-bounded products
                          (options, futures, bonds, repo, ...).  Forwarded
                          to ``StatsClient``.  Accepts a
                          :class:`~backend.quant.stats.constants.OPTIONS_PERIODS`
                          member, its ``display_name`` string, or a raw
                          number of seconds.
        src_task_id:      Optional source task id for provenance.
        thread_id:        LangGraph thread id; forwarded to ``input_raw`` for
                          provenance (injected by the @task layer, not set by
                          callers).
    """

    symbol: str = Field(description="Instrument ticker, e.g. 'AAPL'.")
    period: str = Field(default="1mo", description="Aggregation period, e.g. '1d', '1mo'.")
    text_content: str | None = Field(default=None, description="Free-form text to inject.")
    json_input: dict | None = Field(default=None, description="Injected OHLCV matrix or StatsRecord dict.")
    maturity_horizon: Any = Field(default=None, description="Horizon for time-bounded products (options, futures, bonds, repo, ...). Accepts a OPTIONS_PERIODS member, its display_name string, or a raw number of seconds. None → ONE_YEAR.")
    pipeline: str | None = Field(
        default=None,
        description=(
            "Explicit pipeline hint ('ohlcv', 'options', 'futures') forwarded by "
            "the hosting node. When provided, it takes precedence over symbol-"
            "based heuristics in the top-level handler."
        ),
    )
    src_task_id: str | None = Field(default=None, description="Source task id for provenance.")
    thread_id: str | None = Field(default=None, description="Thread id for input_raw provenance.")


class GetStatsOutput(BaseModel):
    """Output from the get_stats task.

    Attributes:
        stats_record: Resolved :class:`StatsRecord` (OHLCV matrix or stub).
                      ``None`` when the provider chain returned no data --
                      the ``note`` field then carries a short reason.
        from_cache:   ``True`` when served from a fresh ``input_raw`` entry.
        pipeline:     Record category: ``'ohlcv'`` (default), ``'options'``,
                      or ``'text'``.
        note:         Free-form status line, set when ``stats_record`` is
                      missing or to surface a non-fatal warning.
    """

    stats_record: StatsRecord | None = None
    from_cache: bool = Field(default=False)
    pipeline: str = Field(default=STATS_DATA_TYPE.OHLCV.value)
    note: str | None = None


__all__ = ["GetStatsInput", "GetStatsOutput"]
