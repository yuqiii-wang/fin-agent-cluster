"""calculate_corr — common NodeTask to compute pairwise Pearson correlation of close prices.

Fetches close-price series for a list of equity symbols from
``fin_markets.quant_stats`` and computes the full Pearson correlation matrix
using ``pandas``.

Design notes
------------
* Only symbols with sufficient data (≥ 2 overlapping bars after alignment) are
  included; missing symbols are listed in :attr:`CalculateCorrOutput.skipped_symbols`.
* Close-price series are **inner-joined** by ``bar_time`` so only bars present
  for all symbols contribute to the correlation.  This prevents misaligned data
  (e.g. different trading sessions) from skewing results.
* The lookback window is approximated from ``window_bars`` × the calendar days
  per granularity bar, with a 2× safety buffer for weekends and public holidays.

Execution layers
----------------
LangGraph layer (``_calculate_corr_task`` decorated with ``@task``):
    Calls ``create_task(..., view_type="Stats")``, delegates to the Celery
    completion worker, returns ``TaskOutput`` on success or
    ``complete_task(failed=True)`` on error.

Celery layer (``_handler``):
    1. Queries ``quant_stats`` for each symbol's close-price bars in parallel.
    2. Aligns series by ``bar_time`` (inner join).
    3. Computes Pearson correlation matrix via ``pandas``.
    4. Returns a nested dict correlation matrix.

Public exports
--------------
``calculate_corr``  — ``NodeTask`` instance.
``HANDLERS``        — dict slice for ``backend.langgraph.nodes.HANDLERS``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.db.postgres import raw_conn
from backend.db.postgres.queries.fin_markets_quant import OhlcvStatsSQL
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.errors.codes import (
    STATS_TASK_CORR_INSUFFICIENT_DATA,
)
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask
from backend.quant.stats import compute_pearson_matrix, STATS_VIEW_TYPE

logger = logging.getLogger(__name__)

_TASK_NAME = "calculate_corr"

# Approximate calendar-day span per bar for the supported granularities.
# Used to compute a safe lookback start date from window_bars.
_GRANULARITY_CALENDAR_DAYS: dict[str, float] = {
    "1min": 0.001,    # ~1.4 min per calendar day
    "5min": 0.005,
    "15min": 0.016,
    "30min": 0.031,
    "1h": 0.154,      # 1 trading hour ≈ 1/6.5 trading day, calendar ≈ 1/6.5 × 1.4
    "2h": 0.308,
    "1day": 1.4,      # accounts for weekends
    "1mo": 32.0,
}

_MIN_BARS_FOR_CORR = 2

# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------

class CalculateCorrInput(BaseModel):
    """Input for the calculate_corr task.

    Attributes:
        symbols:     List of equity ticker symbols to correlate, e.g. ``['AAPL', 'MSFT']``.
        granularity: Bar granularity to query from ``quant_stats``, e.g. ``'1day'``.
        window_bars: Number of most-recent bars to include per symbol.
    """

    symbols: list[str] = Field(min_length=2, description="Equity tickers to correlate.")
    granularity: str = Field(description="Bar granularity: '1h', '1day', '1mo', etc.")
    window_bars: int = Field(default=252, ge=2, description="Lookback bar count per symbol.")

class CalculateCorrOutput(BaseModel):
    """Output from the calculate_corr task.

    Attributes:
        matrix:            Nested dict ``{symbol → {symbol → correlation}}``.
                           Pearson correlation coefficients in [-1.0, 1.0] on close prices.
        indicator_matrices: Per-indicator Pearson matrices keyed by column name
                           (``"sma_20"``, ``"sma_50"``, ``"ema_12"``, ``"ema_26"``).
                           Only populated for indicators with sufficient aligned data;
                           absent entries mean the indicator series had too many NaNs
                           (e.g. early bars before enough history existed).
        included_symbols:  Symbols that had enough aligned close-price data.
        skipped_symbols:   Symbols excluded due to insufficient close-price data.
        bar_count:         Number of aligned close-price bars used for ``matrix``.
    """

    matrix: dict[str, dict[str, float]]
    indicator_matrices: dict[str, dict[str, dict[str, float]]] = Field(
        default_factory=dict,
        description="Per-indicator Pearson matrices: {indicator → {symbol → {symbol → r}}}.",
    )
    included_symbols: list[str]
    skipped_symbols: list[str]
    bar_count: int
    df_split: dict[str, Any] = Field(
        default_factory=dict,
        description="Correlation matrix as a pandas split-orient dict for DataFrame stats view.",
    )
    stats_views: list[str] = Field(
        default_factory=lambda: [STATS_VIEW_TYPE.DATA_FRAME.value],
        description="Stats view types to render for this task output.",
    )

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lookback_start(granularity: str, window_bars: int) -> datetime:
    """Compute the earliest bar_time to query given a granularity and bar count.

    Uses a 2× safety buffer on top of the calendar-day estimate to account for
    weekends, public holidays, and sparse data periods.

    Args:
        granularity: Bar granularity string.
        window_bars: Target number of bars to include.

    Returns:
        UTC :class:`datetime` to use as the ``bar_time >=`` filter.
    """
    cal_days_per_bar = _GRANULARITY_CALENDAR_DAYS.get(granularity, 1.4)
    total_days = max(30.0, cal_days_per_bar * window_bars * 2)
    return datetime.now(timezone.utc) - timedelta(days=total_days)

async def _fetch_close_series(symbol: str, granularity: str, start_dt: datetime) -> pd.Series:
    """Query close prices for *symbol* from ``quant_stats`` and return as a Series.

    Args:
        symbol:      Uppercase ticker symbol.
        granularity: Bar granularity.
        start_dt:    Earliest bar_time to include (UTC).

    Returns:
        :class:`pandas.Series` indexed by ``bar_time`` (UTC aware datetimes)
        with close prices as values, named *symbol*.  Empty Series when no
        rows are found.
    """
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(OhlcvStatsSQL.GET_BARS_IN_WINDOW, (symbol, granularity, start_dt))
        rows = await cur.fetchall()

    if not rows:
        return pd.Series(name=symbol, dtype=float)

    bar_times = [row["bar_time"] for row in rows]
    closes = [float(row["close"]) if row["close"] is not None else float("nan") for row in rows]
    return pd.Series(closes, index=pd.DatetimeIndex(bar_times), name=symbol)

# SMA/EMA indicator columns fetched for cross-symbol correlation.
_SMA_EMA_COLS: tuple[str, ...] = ("sma_20", "sma_50", "ema_12", "ema_26")

async def _fetch_sma_ema_series(
    symbol: str, granularity: str, start_dt: datetime
) -> dict[str, pd.Series]:
    """Query SMA/EMA indicator values for *symbol* from ``quant_stats``.

    Returns a dict of column name → Series (indexed by bar_time, named *symbol*).
    Bars where an indicator is ``NULL`` (not yet computed due to insufficient history)
    are stored as ``NaN`` and will be dropped during inner-join alignment.

    Args:
        symbol:      Uppercase ticker symbol.
        granularity: Bar granularity.
        start_dt:    Earliest bar_time to include (UTC).

    Returns:
        Dict mapping each indicator column to a :class:`pandas.Series`.
        Empty dict when no rows are found.
    """
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            OhlcvStatsSQL.GET_SMA_EMA_BARS_IN_WINDOW, (symbol, granularity, start_dt)
        )
        rows = await cur.fetchall()

    if not rows:
        return {}

    bar_times = pd.DatetimeIndex([row["bar_time"] for row in rows])
    return {
        col: pd.Series(
            [float(row[col]) if row[col] is not None else float("nan") for row in rows],
            index=bar_times,
            name=symbol,
        )
        for col in _SMA_EMA_COLS
    }

# ---------------------------------------------------------------------------
# Celery layer — business logic
# ---------------------------------------------------------------------------

async def _handler(payload: dict) -> dict:
    """Fetch close-price and SMA/EMA series for all symbols and compute Pearson correlation matrices.

    Args:
        payload: Serialised :class:`CalculateCorrInput` dict.

    Returns:
        Serialised :class:`CalculateCorrOutput` dict.  Returns an empty matrix
        (with a warning log) when fewer than 2 symbols have sufficient aligned data.
    """
    inp = CalculateCorrInput.model_validate(payload)
    symbols = [s.upper() for s in inp.symbols]
    start_dt = _lookback_start(inp.granularity, inp.window_bars)

    # Fetch close-price series and SMA/EMA indicator series concurrently.
    close_series_list, sma_ema_data_list = await asyncio.gather(
        asyncio.gather(*[_fetch_close_series(sym, inp.granularity, start_dt) for sym in symbols]),
        asyncio.gather(*[_fetch_sma_ema_series(sym, inp.granularity, start_dt) for sym in symbols]),
    )

    # --- close-price Pearson correlation (primary) ---
    close_map: dict[str, pd.Series] = {s.name: s for s in close_series_list if not s.empty}
    skipped_symbols: list[str] = [sym for sym in symbols if sym not in close_map]

    if len(close_map) < 2:
        logger.warning(
            "[%s] Fewer than 2 symbols have bar data for granularity=%r; skipped=%s — returning empty corr",
            STATS_TASK_CORR_INSUFFICIENT_DATA, inp.granularity, skipped_symbols,
        )
        return CalculateCorrOutput(
            matrix={}, bar_count=0, indicator_matrices={},
            included_symbols=[], skipped_symbols=skipped_symbols,
        ).model_dump()

    matrix, bar_count = compute_pearson_matrix(close_map, inp.window_bars)
    if not matrix:
        logger.warning(
            "[%s] Only %d aligned bar(s) after inner-join; need at least %d — returning empty corr",
            STATS_TASK_CORR_INSUFFICIENT_DATA, bar_count, _MIN_BARS_FOR_CORR,
        )
        return CalculateCorrOutput(
            matrix={}, bar_count=bar_count, indicator_matrices={},
            included_symbols=[], skipped_symbols=skipped_symbols,
        ).model_dump()

    # --- SMA/EMA indicator Pearson correlations ---
    # For each indicator column build a {symbol → Series} map, then compute
    # the Pearson matrix.  Indicators with insufficient non-NaN overlap are
    # silently omitted (early bars lack enough history to compute SMA_200 etc.).
    indicator_matrices: dict[str, dict[str, dict[str, float]]] = {}
    for col in _SMA_EMA_COLS:
        ind_map = {
            sym: data[col]
            for sym, data in zip(symbols, sma_ema_data_list)
            if col in data and not data[col].empty
        }
        if len(ind_map) < 2:
            continue
        ind_matrix, _ = compute_pearson_matrix(ind_map, inp.window_bars)
        if ind_matrix:
            indicator_matrices[col] = ind_matrix

    symbols_in = list(matrix.keys())
    df_split: dict[str, Any] = {
        "index": symbols_in,
        "columns": symbols_in,
        "data": [
            [round(matrix[r].get(c, 0.0), 4) for c in symbols_in]
            for r in symbols_in
        ],
        "index_label": "Symbol",
    }
    return CalculateCorrOutput(
        matrix=matrix,
        indicator_matrices=indicator_matrices,
        included_symbols=symbols_in,
        skipped_symbols=skipped_symbols,
        bar_count=bar_count,
        df_split=df_split,
    ).model_dump()

# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------

async def _calculate_corr_task(
    task_input: TaskInput[CalculateCorrInput],
) -> TaskOutput[CalculateCorrOutput]:
    """LangGraph @task: delegates calculate_corr to the Celery completion worker.

    Args:
        task_input: Typed envelope with :class:`~backend.langgraph.models.models.TaskContext`
                    and :class:`CalculateCorrInput` content.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`CalculateCorrOutput`.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump()

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type="Stats", stats_views=[STATS_VIEW_TYPE.DATA_FRAME.value],
    )
    try:
        result = await delegate_completion(
            ctx.thread_id, ctx.task_id, ctx.node_id, ctx.node_name, ctx.task_name, payload,
        )
    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            failed=True, error=str(exc),
        )
        raise

    output = CalculateCorrOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)

# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

calculate_corr = NodeTask(
    name=_TASK_NAME,
    description=(
        "Compute the pairwise Pearson correlation matrix of close-price series for a list of "
        "equity symbols, fetching OHLCV bar data from fin_markets.quant_stats.  "
        "Returns the full correlation matrix, included/skipped symbols, and aligned bar count."
    ),
    input_type=CalculateCorrInput,
    output_type=CalculateCorrOutput,
    task_fn=_calculate_corr_task,
    handler=_handler,
)

HANDLERS: dict = {_TASK_NAME: _handler}

__all__ = ["calculate_corr", "CalculateCorrInput", "CalculateCorrOutput", "HANDLERS"]
