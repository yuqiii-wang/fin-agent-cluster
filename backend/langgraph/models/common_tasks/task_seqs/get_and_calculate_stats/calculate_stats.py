"""calculate_stats — entry NodeTask dispatching OHLCV indicator computation.

Routes the calculation payload to the appropriate instrument-specific handler
in :mod:`calculation_utils`:

- All OHLCV-based instruments (equity, index, crypto, precious_metal, commodity) →
  :func:`~calculation_utils.calculate_stock_stats.calculate_stock_stats_handler`

Execution layers
----------------
LangGraph layer (``_calculate_stats_task`` decorated with ``@task``):
    Calls ``create_task(..., view_type="Stats")``, delegates to the Celery
    completion worker, returns ``TaskOutput`` on success or ``complete_task(failed=True)``
    and re-raises on error.

Celery layer (``_handler``):
    Dispatches to the instrument-specific handler from ``calculation_utils``.

Public exports
--------------
``calculate_stats``      — ``NodeTask`` instance.
``CalculateStatsInput``  — Pydantic input model (alias for ``CalculateStockStatsInput``).
``CalculateStatsOutput`` — Pydantic output model (alias for ``CalculateStockStatsOutput``).
``HANDLERS``             — dict slice for ``backend.langgraph.nodes.HANDLERS``.
"""

from __future__ import annotations

from langgraph.func import task

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculate_stock_stats import (
    CalculateStockStatsInput,
    CalculateStockStatsOutput,
    calculate_stock_stats_handler,
)
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask

_TASK_NAME = "calculate_stats"

# Public aliases so existing importers of CalculateStatsInput/Output continue to work.
CalculateStatsInput = CalculateStockStatsInput
CalculateStatsOutput = CalculateStockStatsOutput


# ---------------------------------------------------------------------------
# Celery layer — entry dispatcher
# ---------------------------------------------------------------------------


async def _handler(payload: dict) -> dict:
    """Dispatch the calculate_stats payload to the appropriate instrument handler.

    Args:
        payload: Serialised :class:`CalculateStatsInput` dict.

    Returns:
        Serialised :class:`CalculateStatsOutput` dict.
    """
    return await calculate_stock_stats_handler(payload)


# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------


@task
async def _calculate_stats_task(
    task_input: TaskInput[CalculateStatsInput],
) -> TaskOutput[CalculateStatsOutput]:
    """LangGraph @task: delegates calculate_stats to the Celery completion worker.

    Args:
        task_input: Typed envelope with :class:`~backend.langgraph.models.models.TaskContext`
                    and :class:`CalculateStatsInput` content.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`CalculateStatsOutput`.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump(mode="json")

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type="Stats",
        stats_views=["CandleStick"],
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

    output = CalculateStatsOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)


# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

calculate_stats = NodeTask(
    name=_TASK_NAME,
    description=(
        "Compute a full suite of technical indicators (SMA, EMA, MACD, RSI, Bollinger Bands, "
        "ATR, ADX, Aroon, Stochastic, Williams %R, CCI, MFI, ROC, NATR, VWAP, OBV, A/D) "
        "from an OHLCV StatsRecord and upsert each bar into fin_markets.quant_stats."
    ),
    input_type=CalculateStatsInput,
    output_type=CalculateStatsOutput,
    task_fn=_calculate_stats_task,
    handler=_handler,
)

HANDLERS: dict = {_TASK_NAME: _handler}

__all__ = ["calculate_stats", "CalculateStatsInput", "CalculateStatsOutput", "HANDLERS"]
