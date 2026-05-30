"""calculate_fundamental_stats — NodeTask wrapping the fundamental aggregation handler.

Routes the aggregated multi-endpoint payload to
:func:`~calculation_utils.calculate_fundamental_stats.calculate_fundamental_stats_handler`
which merges provider fields, derives index membership from the exchange, and
inserts a row into ``fin_markets.quant_static_stats``.

Execution layers
----------------
LangGraph layer (``_calculate_fundamental_stats_task`` decorated with ``@task``):
    Calls ``create_task(..., view_type="Fundamentals")``, delegates to the Celery
    completion worker, and returns a ``TaskOutput``.

Celery layer (``_handler``):
    Delegates to :func:`calculate_fundamental_stats_handler`.

Public exports
--------------
``calculate_fundamental_stats``      — ``NodeTask`` instance.
``CalculateFundamentalStatsInput``   — Pydantic input model.
``CalculateFundamentalStatsOutput``  — Pydantic output model.
``HANDLERS``                         — dict slice for Celery handler registration.
"""

from __future__ import annotations

from langgraph.func import task

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculate_fundamental_stats import (
    CalculateFundamentalStatsInput,
    CalculateFundamentalStatsOutput,
    calculate_fundamental_stats_handler,
)
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask

_TASK_NAME = "calculate_fundamental_stats"


# ---------------------------------------------------------------------------
# Celery layer — entry dispatcher
# ---------------------------------------------------------------------------


async def _handler(payload: dict) -> dict:
    """Dispatch the calculate_fundamental_stats payload to the aggregation handler.

    Args:
        payload: Serialised :class:`CalculateFundamentalStatsInput` dict.

    Returns:
        Serialised :class:`CalculateFundamentalStatsOutput` dict.
    """
    return await calculate_fundamental_stats_handler(payload)


# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------


@task
async def _calculate_fundamental_stats_task(
    task_input: TaskInput[CalculateFundamentalStatsInput],
) -> TaskOutput[CalculateFundamentalStatsOutput]:
    """LangGraph @task: delegates calculate_fundamental_stats to the Celery completion worker.

    Args:
        task_input: Typed envelope with :class:`~backend.langgraph.models.models.TaskContext`
                    and :class:`CalculateFundamentalStatsInput` content.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`CalculateFundamentalStatsOutput`.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump(mode="json")

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type="Fundamentals",
        stats_views=[],
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

    output = CalculateFundamentalStatsOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)


# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

calculate_fundamental_stats = NodeTask(
    name=_TASK_NAME,
    description=(
        "Aggregate raw fundamental data from multiple endpoints (income_statement, balance_sheet, "
        "cash_flow, key_metrics), normalise provider field names, derive index membership from "
        "exchange, and upsert a row into fin_markets.quant_static_stats."
    ),
    input_type=CalculateFundamentalStatsInput,
    output_type=CalculateFundamentalStatsOutput,
    task_fn=_calculate_fundamental_stats_task,
    handler=_handler,
)

HANDLERS: dict = {_TASK_NAME: _handler}

__all__ = [
    "calculate_fundamental_stats",
    "CalculateFundamentalStatsInput",
    "CalculateFundamentalStatsOutput",
    "HANDLERS",
]
