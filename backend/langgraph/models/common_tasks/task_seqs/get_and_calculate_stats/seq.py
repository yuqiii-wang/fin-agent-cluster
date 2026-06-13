"""get_and_calculate_stats -- TaskSeq pipeline: fetch raw market data then compute stats.

get_stats -- fetch by requesting a stats provider (yfinance/FMP/mock) with
    provider- and period-fallback, or inject ``json_input`` / ``text_content``
    handed down from a previous task.  Hard failure: if this step fails, the
    whole pipeline fails and raises.
calculate_stats -- dispatch by ``pipeline`` label to the appropriate handler:
    - ``'ohlcv'`` / ``'futures'`` -> calculate_ohlcv_stats (compute indicators,
      upsert quant_stats / quant_index_stats / quant_futures_stats)
    - ``'options'`` -> calculate_option_stats (volatility smile, open interest)
    - ``'text'`` (or anything else) -> short-circuit with a zero-row stub
"""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)

_SEQ_NAME = "get_and_calculate_stats"


async def _pipeline(
    run_task_fn: Callable[..., Awaitable[Any]],
    ctx: NodeContext,
    seq_input: GetAndCalculateStatsInput,
) -> GetAndCalculateStatsOutput:
    """Run get_stats -> calculate_stats.

    Args:
        run_task_fn: Bound ``self.run_task`` from the hosting node.
        ctx:         Current node context.
        seq_input:   Typed pipeline input.

    Returns:
        Combined output from both tasks.
    """
    # 1. get_stats -- hard failure (propagates).
    gs_result = await run_task_fn(
        get_stats,
        ctx,
        GetStatsInput(
            symbol=seq_input.symbol,
            period=seq_input.period,
            text_content=seq_input.text_content,
            json_input=seq_input.json_input,
            maturity_horizon=seq_input.maturity_horizon,
            src_task_id=seq_input.src_task_id,
        ),
    )
    gs_output = gs_result.content

    # 2. calculate_stats -- compute indicators (or short-circuit for non-OHLCV).
    #    ``pipeline`` from the pipeline input wins, falling back to whatever
    #    the stats record reported. This lets callers explicitly target
    #    "options" or "futures" handlers.
    effective_pipeline = seq_input.pipeline or gs_output.pipeline or "ohlcv"
    cs_result = await run_task_fn(
        calculate_stats,
        ctx,
        CalculateStatsInput(
            stats_record=gs_output.stats_record,
            from_cache=gs_output.from_cache or effective_pipeline != "ohlcv",
            pipeline=effective_pipeline,
        ),
    )

    return GetAndCalculateStatsOutput(
        get_stats=gs_output,
        calculate_stats=cs_result.content,
    )


get_and_calculate_stats: TaskSeq[GetAndCalculateStatsInput, GetAndCalculateStatsOutput] = TaskSeq(
    name=_SEQ_NAME,
    description=(
        "Sequential pipeline: resolve an OHLCV StatsRecord (get_stats -- provider "
        "fetch with provider/period fallback, or json_input/text_content injection), "
        "then compute technical indicators and upsert each bar into "
        "fin_markets.quant_stats (calculate_stats)."
    ),
    tasks=[get_stats, calculate_stats],
    input_type=GetAndCalculateStatsInput,
    output_type=GetAndCalculateStatsOutput,
    pipeline_fn=_pipeline,
)

__all__ = ["get_and_calculate_stats"]