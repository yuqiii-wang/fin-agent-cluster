"""task — LangGraph @task orchestration and NodeTask registration for options stats.

Provides:
- ``_calculate_option_stats_task``: LangGraph ``@task`` delegating to Celery.
- ``calculate_option_stats``:       ``NodeTask`` instance for registration.
- ``HANDLERS``:                     dict slice for Celery handler registration.
"""

from __future__ import annotations

from langgraph.func import task

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask

from .handler import _handler
from .models import CalculateOptionStatsInput, CalculateOptionStatsOutput

_TASK_NAME = "calculate_option_stats"


@task
async def _calculate_option_stats_task(
    task_input: TaskInput[CalculateOptionStatsInput],
) -> TaskOutput[CalculateOptionStatsOutput]:
    """LangGraph @task: delegates calculate_option_stats to the Celery completion worker.

    Args:
        task_input: Typed envelope with :class:`~backend.langgraph.models.models.TaskContext`
                    and :class:`CalculateOptionStatsInput` content.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`CalculateOptionStatsOutput`.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump(mode="json")

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type="Stats",
        stats_views=["VolatilitySmile"],
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

    output = CalculateOptionStatsOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)


calculate_option_stats = NodeTask(
    name=_TASK_NAME,
    description=(
        "Persist an options chain in two steps: upsert each call/put contract into "
        "fin_markets.quant_options_stats, then aggregate per expiry into "
        "fin_markets.quant_derivative_stats by estimating the underlying price where the "
        "call and put breakevens meet at the ATM strike."
    ),
    input_type=CalculateOptionStatsInput,
    output_type=CalculateOptionStatsOutput,
    task_fn=_calculate_option_stats_task,
    handler=_handler,
)

HANDLERS: dict = {_TASK_NAME: _handler}

__all__ = [
    "calculate_option_stats",
    "HANDLERS",
]
