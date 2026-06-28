"""calculate_stats -- entry NodeTask dispatching OHLCV indicator computation.

Routes the calculation payload to the appropriate instrument-specific handler
in :mod:`calculation_utils` based on the ``StatsRecord.id`` prefix:

- ``json-options-*``  -> no-op (options stats are computed by ``calculate_option_stats``)
- ``json-futures-*``  -> no-op (futures stats calculation not yet implemented)
- all other records   -> :func:`~calculation_utils.calculate_ohlcv_stats.calculate_ohlcv_stats_handler`
  (equity, index, crypto, precious_metal, commodity -- any OHLCV-based record)

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
``calculate_stats``      -- ``NodeTask`` instance.
``CalculateStatsInput``  -- Pydantic input model (alias for ``CalculateOhlcvStatsInput``).
``CalculateStatsOutput`` -- Pydantic output model (alias for ``CalculateOhlcvStatsOutput``).
``HANDLERS``             -- dict slice for ``backend.langgraph.nodes.HANDLERS``.
"""

from __future__ import annotations

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.models import CalculateStatsBaseOutput
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculate_ohlcv_stats import (
    CalculateOhlcvStatsInput,
    CalculateOhlcvStatsOutput,
    calculate_ohlcv_stats_handler,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculate_option_stats import (
    CalculateOptionStatsInput,
    CalculateOptionStatsOutput,
    calculate_option_stats_handler,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculate_futures_stats import (
    CalculateFuturesStatsInput,
    CalculateFuturesStatsOutput,
    calculate_futures_stats_handler,
)
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask
from backend.quant.stats import STATS_DATA_TYPE, STATS_VIEW_TYPE

_TASK_NAME = "calculate_stats"

# Public aliases so existing importers of CalculateStatsInput/Output continue to work.
CalculateStatsInput = CalculateOhlcvStatsInput
CalculateStatsOutput = CalculateStatsBaseOutput

# ---------------------------------------------------------------------------
# Celery layer -- entry dispatcher
# ---------------------------------------------------------------------------

async def _handler(payload: dict) -> dict:
    """Dispatch the calculate_stats payload to the appropriate instrument handler.

    Routes by ``pipeline`` from the payload:
    - ``'ohlcv'`` (default) -> :func:`calculate_ohlcv_stats_handler`.
    - ``'options'`` -> :func:`calculate_option_stats_handler`.
    - ``'futures'`` -> :func:`calculate_futures_stats_handler` (reuses the
      quant_stats OHLCV indicator pipeline internally; stamps output with
      ``maturity_label`` / ``maturity_seconds`` / ``pipeline='futures'``).
    """
    pipeline = payload.get("pipeline", STATS_DATA_TYPE.OHLCV.value)

    if pipeline == STATS_DATA_TYPE.OHLCV.value:
        CalculateOhlcvStatsInput.model_validate(payload)
        return await calculate_ohlcv_stats_handler(payload)
    elif pipeline == STATS_DATA_TYPE.OPTIONS.value:
        CalculateOptionStatsInput.model_validate(payload)
        return await calculate_option_stats_handler(payload)
    elif pipeline == STATS_DATA_TYPE.FUTURES.value:
        CalculateFuturesStatsInput.model_validate(payload)
        return await calculate_futures_stats_handler(payload)
    else:
        # For other pipeline types, return a zero-row stub
        return CalculateOhlcvStatsOutput(
            rows_upserted=0,
            symbol="",
            granularity="",
            source="",
            df_split={},
            stats_views=[STATS_VIEW_TYPE.DATA_FRAME.value, STATS_VIEW_TYPE.CANDLE_STICK.value],
        ).model_dump()

# ---------------------------------------------------------------------------
# LangGraph layer -- @task orchestration
# ---------------------------------------------------------------------------

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
        stats_views=[STATS_VIEW_TYPE.CANDLE_STICK.value],
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

    # Validate against the correct output model based on pipeline
    pipeline = payload.get("pipeline", STATS_DATA_TYPE.OHLCV.value)
    if pipeline == STATS_DATA_TYPE.OPTIONS.value:
        output = CalculateOptionStatsOutput.model_validate(result)
    elif pipeline == STATS_DATA_TYPE.FUTURES.value:
        output = CalculateFuturesStatsOutput.model_validate(result)
    else:
        output = CalculateOhlcvStatsOutput.model_validate(result)
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
