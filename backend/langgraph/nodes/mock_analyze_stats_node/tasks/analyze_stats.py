"""analyze_stats — NodeTask for analyze_stats_node.

Execution layers
----------------
LangGraph layer (``_analyze_stats_task``):
    Calls ``create_task``, delegates to a Celery completion worker via
    ``delegate_completion``, and calls ``complete_task`` on success / failure.

Celery layer (``_handler``):
    Reconstructs the pandas DataFrame from the ``df_split`` (split orient) stored
    in ``ReadStatsOutput``, then delegates metric computation to
    :func:`~backend.quant.stats.metrics.compute_metrics`.
"""

from __future__ import annotations

import logging

from langgraph.func import task

from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.mock_analyze_stats_node.models import AnalyzeStatsInput, AnalyzeStatsOutput
from backend.celery_task.workers.task_delegation import delegate_completion

logger = logging.getLogger(__name__)

_TASK_NAME = "analyze_stats"


async def _handler(payload: dict) -> dict:
    """Analyse OHLCV stats data and produce key metrics + narrative.

    Reads ``df_split`` from ``stats_data`` (the serialised ``ReadStatsOutput``),
    delegates metric computation to
    :func:`~backend.quant.stats.metrics.compute_metrics`, and builds a
    human-readable narrative.

    Args:
        payload: Serialised ``AnalyzeStatsInput`` dict.

    Returns:
        Serialised ``AnalyzeStatsOutput`` dict.
    """
    from backend.quant.stats.metrics import compute_metrics

    inp = AnalyzeStatsInput.model_validate(payload)
    stats_data = inp.stats_data
    symbol = stats_data.get("symbol", "")
    df_split: dict = stats_data.get("df_split", {})

    metrics = compute_metrics(df_split)
    trend = metrics.get("trend", "unknown")
    ret = metrics.get("return_pct", 0.0)
    vol = metrics.get("volatility", 0.0)

    narrative = (
        f"{symbol} shows a {trend} over the analysis period with a period return of "
        f"{ret:+.2f}% and daily volatility of {vol:.2f}%. "
        f"Data spans {metrics.get('bar_count', 0)} bars "
        f"(first close: {metrics.get('first_close', 'N/A')}, "
        f"last close: {metrics.get('last_close', 'N/A')})."
    )

    return AnalyzeStatsOutput(
        symbol=symbol,
        stats_analysis=narrative,
        key_metrics=metrics,
    ).model_dump()


@task
async def _analyze_stats_task(
    task_input: TaskInput[AnalyzeStatsInput],
) -> TaskOutput[AnalyzeStatsOutput]:
    """LangGraph @task: delegates analyze_stats to a Celery completion worker.

    Args:
        task_input: Typed envelope with TaskContext and AnalyzeStatsInput content.

    Returns:
        TaskOutput wrapping AnalyzeStatsOutput.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump()

    await create_task(ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload, view_type="Stats")
    try:
        result = await delegate_completion(
            ctx.thread_id, ctx.task_id, ctx.node_id, ctx.node_name, ctx.task_name, payload
        )
    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            failed=True, error=str(exc), view_type="Stats",
        )
        raise
    output = AnalyzeStatsOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)


analyze_stats = NodeTask(
    name=_TASK_NAME,
    description=(
        "Analyse OHLCV market statistics to compute period return, volatility, "
        "trend direction, and produce a narrative summary for the equity symbol."
    ),
    input_type=AnalyzeStatsInput,
    output_type=AnalyzeStatsOutput,
    task_fn=_analyze_stats_task,
    handler=_handler,
)
