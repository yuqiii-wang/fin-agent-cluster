"""prepare_fundamentals — TaskSeq pipeline: fan-out fetch fundamentals then aggregate.

Orchestration
-------------
1. ``get_fundamentals`` (×N, parallel) — fetch each requested endpoint type in parallel
   (income_statement, balance_sheet, cash_flow, key_metrics).  Each call stores its raw
   JSON response in ``fin_markets.input_raw`` with a 24-hour TTL.
2. ``calculate_fundamental_stats`` (×1) — aggregate all JSON payloads, normalise field
   names from FMP / yfinance conventions, and insert a row into
   ``fin_markets.quant_static_stats``.

The fan-out step uses ``asyncio.gather`` so all ``get_fundamentals`` invocations run
concurrently.  ``calculate_fundamental_stats`` only starts after all fetches complete.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculate_fundamental_stats import (
    CalculateFundamentalStatsInput,
    FundamentalsDataItem,
)
from backend.langgraph.models.common_tasks.task_seqs.prepare_fundamentals.calculate_fundamental_stats import (
    calculate_fundamental_stats,
)
from backend.langgraph.models.common_tasks.task_seqs.prepare_fundamentals.get_fundamentals import (
    GetFundamentalsInput,
    get_fundamentals,
)
from backend.langgraph.models.common_tasks.task_seqs.prepare_fundamentals.models import (
    PrepareFundamentalsInput,
    PrepareFundamentalsOutput,
)
from backend.langgraph.models.models import NodeContext
from backend.langgraph.models.task_seq import TaskSeq

_SEQ_NAME = "prepare_fundamentals"


async def _pipeline(
    run_task_fn: Callable[..., Awaitable[Any]],
    ctx: NodeContext,
    seq_input: PrepareFundamentalsInput,
) -> PrepareFundamentalsOutput:
    """Fan-out to parallel get_fundamentals calls, then aggregate in calculate_fundamental_stats.

    Args:
        run_task_fn: Bound ``self.run_task`` from the hosting node.
        ctx:         Current node context.
        seq_input:   Typed pipeline input.

    Returns:
        Combined output from all fetch tasks and the single aggregation task.
    """
    fetch_results = await asyncio.gather(*[
        run_task_fn(
            get_fundamentals,
            ctx,
            GetFundamentalsInput(
                symbol=seq_input.symbol,
                endpoint_type=endpoint_type,
            ),
        )
        for endpoint_type in seq_input.endpoint_types
    ])

    items = [
        FundamentalsDataItem(
            endpoint_type=result.content.endpoint_type,
            json_data=result.content.json_data,
        )
        for result in fetch_results
    ]

    calc_result = await run_task_fn(
        calculate_fundamental_stats,
        ctx,
        CalculateFundamentalStatsInput(
            symbol=seq_input.symbol,
            items=items,
        ),
    )

    return PrepareFundamentalsOutput(
        get_fundamentals=[result.content for result in fetch_results],
        calculate_fundamental_stats=calc_result.content,
    )


prepare_fundamentals: TaskSeq[PrepareFundamentalsInput, PrepareFundamentalsOutput] = TaskSeq(
    name=_SEQ_NAME,
    description=(
        "Fan-out pipeline: fetch fundamental data from multiple endpoints in parallel "
        "(get_fundamentals ×N), then aggregate and upsert into fin_markets.quant_static_stats "
        "(calculate_fundamental_stats ×1)."
    ),
    tasks=[get_fundamentals, calculate_fundamental_stats],
    input_type=PrepareFundamentalsInput,
    output_type=PrepareFundamentalsOutput,
    pipeline_fn=_pipeline,
)

__all__ = ["prepare_fundamentals"]
