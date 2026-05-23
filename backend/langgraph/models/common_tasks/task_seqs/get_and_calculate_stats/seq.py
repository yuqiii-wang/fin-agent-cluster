"""get_and_calculate_stats — TaskSeq pipeline: fetch OHLCV stats then compute indicators.

Orchestration
-------------
1. ``get_stats``       — fetch OHLCV bars + news, cache raw response in ``quant_raw``.
2. ``calculate_stats`` — compute technical indicators, upsert bars to ``quant_stats``.

The ``bypass_calculate`` flag from ``get_stats`` is forwarded to ``calculate_stats``
so that indicator recomputation is skipped when a fresh cache entry already has
corresponding ``quant_stats`` rows.

Each constituent task is unchanged at the Celery and DB persistence layers.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculate_stats import (
    CalculateStatsInput,
    calculate_stats,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats import (
    GetStatsInput,
    get_stats,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.models import (
    GetAndCalculateStatsInput,
    GetAndCalculateStatsOutput,
)
from backend.langgraph.models.models import NodeContext
from backend.langgraph.models.task_seq import TaskSeq

_SEQ_NAME = "get_and_calculate_stats"


async def _pipeline(
    run_task_fn: Callable[..., Awaitable[Any]],
    ctx: NodeContext,
    seq_input: GetAndCalculateStatsInput,
) -> GetAndCalculateStatsOutput:
    """Run get_stats then feed its output into calculate_stats.

    Args:
        run_task_fn: Bound ``self.run_task`` from the hosting node.
        ctx:         Current node context.
        seq_input:   Typed pipeline input.

    Returns:
        Combined output from both tasks.
    """
    gs_result = await run_task_fn(
        get_stats,
        ctx,
        GetStatsInput(
            symbol=seq_input.symbol,
            period=seq_input.period,
            news_limit=seq_input.news_limit,
            bypass_threshold_minutes=seq_input.bypass_threshold_minutes,
        ),
    )
    cs_result = await run_task_fn(
        calculate_stats,
        ctx,
        CalculateStatsInput(
            stats_record=gs_result.content.stats_record,
            bypass=gs_result.content.bypass_calculate,
        ),
    )
    return GetAndCalculateStatsOutput(
        get_stats=gs_result.content,
        calculate_stats=cs_result.content,
    )


get_and_calculate_stats: TaskSeq[GetAndCalculateStatsInput, GetAndCalculateStatsOutput] = TaskSeq(
    name=_SEQ_NAME,
    description=(
        "Sequential pipeline: fetch OHLCV stats and news for a symbol (get_stats), "
        "then compute technical indicators and upsert each bar to quant_stats (calculate_stats)."
    ),
    tasks=[get_stats, calculate_stats],
    input_type=GetAndCalculateStatsInput,
    output_type=GetAndCalculateStatsOutput,
    pipeline_fn=_pipeline,
)

__all__ = ["get_and_calculate_stats"]
