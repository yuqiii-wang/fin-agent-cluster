"""analyze_stats — NodeTask for analyze_stats_node.

Execution layers
----------------
LangGraph layer (``_analyze_stats_task``):
    Calls ``create_task``, delegates to a Celery completion worker via
    ``delegate_completion``, and calls ``complete_task`` on success / failure.

Celery layer (``_handler``):
    Computes key OHLCV-based metrics from the stats_data produced by
    research_subgraph: period return, annualised volatility, trend
    direction, and a human-readable narrative summary.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.func import task

from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.nodes.base.models import TaskInput, TaskOutput
from backend.langgraph.nodes.base.task import NodeTask
from backend.langgraph.nodes.analyze_stats_node.models import AnalyzeStatsInput, AnalyzeStatsOutput
from backend.celery_task.workers.task_delegation import delegate_completion

logger = logging.getLogger(__name__)

_TASK_NAME = "analyze_stats"


def _compute_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive key OHLCV metrics from a list of bar records.

    Args:
        records: List of OHLCV dicts, each expected to have a ``close`` key.

    Returns:
        Dict with ``return_pct``, ``volatility``, ``trend``, ``bar_count``.
    """
    closes = [float(r["close"]) for r in records if "close" in r]
    if len(closes) < 2:
        return {"return_pct": 0.0, "volatility": 0.0, "trend": "unknown", "bar_count": len(closes)}

    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
    period_return = (closes[-1] - closes[0]) / closes[0] * 100

    import statistics
    volatility = statistics.stdev(returns) * 100 if len(returns) > 1 else 0.0

    # Simple trend: compare last third vs first third averages
    third = max(1, len(closes) // 3)
    early_avg = sum(closes[:third]) / third
    late_avg = sum(closes[-third:]) / third
    if late_avg > early_avg * 1.01:
        trend = "uptrend"
    elif late_avg < early_avg * 0.99:
        trend = "downtrend"
    else:
        trend = "sideways"

    return {
        "return_pct": round(period_return, 4),
        "volatility": round(volatility, 4),
        "trend": trend,
        "bar_count": len(closes),
        "first_close": round(closes[0], 4),
        "last_close": round(closes[-1], 4),
    }


async def _handler(payload: dict) -> dict:
    """Analyse OHLCV stats data and produce key metrics + narrative.

    Args:
        payload: Serialised ``AnalyzeStatsInput`` dict.

    Returns:
        Serialised ``AnalyzeStatsOutput`` dict.
    """
    inp = AnalyzeStatsInput.model_validate(payload)
    stats_data = inp.stats_data
    symbol = stats_data.get("symbol", "")
    records: list[dict[str, Any]] = stats_data.get("records", [])

    metrics = _compute_metrics(records)
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

    await create_task(ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload)
    try:
        result = await delegate_completion(
            ctx.thread_id, ctx.task_id, ctx.node_id, ctx.node_name, ctx.task_name, payload
        )
    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            failed=True, error=str(exc),
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
