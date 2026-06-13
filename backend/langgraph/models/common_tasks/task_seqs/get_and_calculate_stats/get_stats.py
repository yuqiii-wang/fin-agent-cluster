"""get_stats -- NodeTask to fetch OHLCV / options StatsRecord for a symbol/period.

Resolves a :class:`~backend.resources.stats.models.StatsRecord` for the
requested ``(symbol, period)`` by delegating to product-specific handlers
inside :mod:`get_stats_utils`:

* :func:`get_stats_utils.handler` dispatches between:
  * ``json_input``  -- directly inject a structured OHLCV matrix or full
    ``StatsRecord`` dict; pipeline auto-detected.
  * ``text_content`` -- inject free-form text as a stub record
    (``pipeline='text'``).
  * external OHLCV fetch -- :func:`get_stats_utils.get_ohlcv_stats_handler`
    with provider + period fallback.
  * external options fetch -- :func:`get_stats_utils.get_options_stats_handler`
    with provider fallback (no period roll-down; horizon drives the cache key).

The raw payload is persisted to ``fin_markets.input_raw`` and re-served on
cache hits.

Execution layers
----------------
LangGraph layer (``_get_stats_task`` decorated with ``@task``):
    Calls ``create_task(..., view_type="Stats")``, delegates to the Celery
    completion worker, and returns a ``TaskOutput``.

Celery layer (``_handler``):
    Dispatches to ``get_stats_utils.handler`` (see above).

Public exports
--------------
``get_stats``       -- ``NodeTask`` instance.
``GetStatsInput``   -- Pydantic input model (re-exported from
                       :mod:`get_stats_utils`).
``GetStatsOutput``  -- Pydantic output model (re-exported from
                       :mod:`get_stats_utils`).
``HANDLERS``        -- dict slice for Celery handler registration.
"""

from __future__ import annotations

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils import (
    GetStatsInput,
    GetStatsOutput,
    handler as _delegate_handler,
)
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask

_TASK_NAME = "get_stats"


async def _handler(payload: dict) -> dict:
    """Celery layer: resolve a StatsRecord via injection or external fetch."""
    return await _delegate_handler(payload)


async def _get_stats_task(
    task_input: TaskInput[GetStatsInput],
) -> TaskOutput[GetStatsOutput]:
    """LangGraph @task: delegates get_stats to the Celery completion worker.

    Args:
        task_input: Typed envelope with
                    :class:`~backend.langgraph.models.models.TaskContext`
                    and :class:`GetStatsInput` content.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`GetStatsOutput`.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump(mode="json")
    payload["thread_id"] = ctx.thread_id

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type="Stats",
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

    output = GetStatsOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)


# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

get_stats: NodeTask[GetStatsInput, GetStatsOutput] = NodeTask(
    name=_TASK_NAME,
    description=(
        "Resolve an OHLCV StatsRecord for a symbol/period: inject a structured "
        "json_input or text_content from a previous task, or fetch from a stats "
        "provider (yfinance/FMP/mock) with provider- and period-fallback. The raw "
        "payload is cached in fin_markets.input_raw."
    ),
    input_type=GetStatsInput,
    output_type=GetStatsOutput,
    task_fn=_get_stats_task,
    handler=_handler,
    cache_ttl_seconds=3600,
)

HANDLERS: dict = {_TASK_NAME: _handler}

__all__ = [
    "get_stats",
    "GetStatsInput",
    "GetStatsOutput",
    "HANDLERS",
]
