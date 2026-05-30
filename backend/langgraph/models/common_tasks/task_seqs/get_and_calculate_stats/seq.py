"""get_and_calculate_stats — TaskSeq pipeline: fetch OHLCV stats then compute indicators.

Orchestration
-------------
1. ``get_stats``       — fetch OHLCV bars + news, cache raw response in ``quant_raw``.
2. ``calculate_stats`` — compute technical indicators, upsert bars to ``quant_stats``.

The ``bypass_calculate`` flag from ``get_stats`` is forwarded to ``calculate_stats``
so that indicator recomputation is skipped when a fresh cache entry already has
corresponding ``quant_stats`` rows.

Each constituent task is unchanged at the Celery and DB persistence layers.

LLM orchestration (agent nodes only)
-------------------------------------
When ``get_stats.is_required_llm_orchestration=True`` and ``get_stats`` raises
(e.g. due to ``json_input`` schema validation failure), ``llm_orchestration_on_failure`` is
invoked to decide recovery:

* ``action="retry_from_step"`` with ``retry_from_step="get_stats"`` and
  ``input_overrides={"json_input": {...corrected...}}`` → retry ``get_stats``
  with the corrected payload.
* any other action → re-raise the original ``get_stats`` exception.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from backend.langgraph.models.common_tasks.llm_orchestration_on_failure import (
    LlmOrchestrationInput,
    StepInfo,
    StepResult,
    llm_orchestration_on_failure,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculate_stats import (
    CalculateStatsInput,
    calculate_stats,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats import (
    GetStatsInput,
    GetStatsOutput,
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

_STEP_GET_STATS = "get_stats"
_STEP_ORDER = [_STEP_GET_STATS]

_STEP_INFO = [
    StepInfo(
        name=_STEP_GET_STATS,
        description=(
            "Fetch OHLCV bars + news for the symbol, or store structured json_input in quant_raw. "
            "json_input must include 'data_type' ('ohlcv', 'options', 'fundamentals') and "
            "the required fields for that type."
        ),
        input_override_schema={
            "json_input": (
                "Corrected structured JSON payload for the get_stats task.  "
                "Must include 'data_type' ('ohlcv', 'options', or 'fundamentals') "
                "plus the required fields for that type: "
                "ohlcv → timestamps (list), series.open/high/low/close (lists); "
                "options → calls/puts (lists of contracts with "
                "  contract_name, options_type, strike) — OR flat 'options' list "
                "  with 'type': 'Call'/'Put' per contract (auto-normalised); "
                "fundamentals → items (list of {endpoint_type, json_data} dicts)."
            ),
        },
    ),
]


async def _get_stats_with_orchestration(
    run_task_fn: Callable[..., Awaitable[Any]],
    ctx: NodeContext,
    gs_input: GetStatsInput,
) -> GetStatsOutput:
    """Attempt get_stats; on failure invoke llm_orchestration_on_failure if flagged.

    On ``get_stats.is_required_llm_orchestration=True`` and a task failure:
      1. Runs ``llm_orchestration_on_failure`` to get a recovery decision.
      2. If ``action="retry_from_step"`` and ``retry_from_step="get_stats"`` with a
         ``json_input`` override: retries ``get_stats`` with the corrected payload.
      3. Otherwise: re-raises the original exception.

    Args:
        run_task_fn: Bound ``self.run_task`` from the hosting node.
        ctx:         Current node context.
        gs_input:    Typed get_stats input.

    Returns:
        :class:`GetStatsOutput` from the successful (possibly retried) call.

    Raises:
        Exception: Original get_stats exception when no recovery is possible.
    """
    try:
        result = await run_task_fn(get_stats, ctx, gs_input)
        return result.content
    except Exception as get_stats_exc:
        if not get_stats.is_required_llm_orchestration:
            raise

        try:
            orch_result = await run_task_fn(
                llm_orchestration_on_failure,
                ctx,
                LlmOrchestrationInput(
                    iteration=1,
                    max_iterations=1,
                    target=gs_input.symbol,
                    objective=f"Fetch or ingest market data for {gs_input.symbol} (period={gs_input.period}).",
                    step_order=_STEP_ORDER,
                    step_info=_STEP_INFO,
                    step_results=[
                        StepResult(
                            step=_STEP_GET_STATS,
                            success=False,
                            output_summary={"symbol": gs_input.symbol, "period": gs_input.period},
                            failure_reason=str(get_stats_exc),
                        )
                    ],
                    failed_step=_STEP_GET_STATS,
                    failure_reason=str(get_stats_exc),
                    context_summary={
                        "symbol": gs_input.symbol,
                        "period": gs_input.period,
                        "json_input_provided": gs_input.json_input is not None,
                    },
                    finish_condition="get_stats completes successfully with valid market data",
                ),
            )
        except Exception as orch_exc:
            logger.error(
                "llm_orchestration_on_failure failed after get_stats failure symbol=%r: %s",
                gs_input.symbol,
                orch_exc,
            )
            raise get_stats_exc from None

        orch_output = orch_result.content
        json_input_override = (orch_output.input_overrides or {}).get("json_input")
        if (
            orch_output.action != "retry_from_step"
            or orch_output.retry_from_step != _STEP_GET_STATS
            or not isinstance(json_input_override, dict)
        ):
            raise get_stats_exc from None

        retry_input = GetStatsInput(
            symbol=gs_input.symbol,
            period=gs_input.period,
            news_limit=gs_input.news_limit,
            bypass_threshold_minutes=gs_input.bypass_threshold_minutes,
            text_content=gs_input.text_content,
            json_input=json_input_override,
            src_task_id=gs_input.src_task_id,
        )
        retry_result = await run_task_fn(get_stats, ctx, retry_input)
        return retry_result.content


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
    gs_input = GetStatsInput(
        symbol=seq_input.symbol,
        period=seq_input.period,
        news_limit=seq_input.news_limit,
        bypass_threshold_minutes=seq_input.bypass_threshold_minutes,
        text_content=seq_input.text_content,
        json_input=seq_input.json_input,
        src_task_id=seq_input.src_task_id,
    )
    gs_content = await _get_stats_with_orchestration(run_task_fn, ctx, gs_input)

    cs_result = await run_task_fn(
        calculate_stats,
        ctx,
        CalculateStatsInput(
            stats_record=gs_content.stats_record,
            bypass=gs_content.bypass_calculate,
        ),
    )
    return GetAndCalculateStatsOutput(
        get_stats=gs_content,
        calculate_stats=cs_result.content,
    )


get_and_calculate_stats: TaskSeq[GetAndCalculateStatsInput, GetAndCalculateStatsOutput] = TaskSeq(
    name=_SEQ_NAME,
    description=(
        "Sequential pipeline: fetch OHLCV stats and news for a symbol (get_stats), "
        "then compute technical indicators and upsert each bar to quant_stats (calculate_stats).  "
        "When json_input validation fails and the hosting node supports it, llm_orchestration_on_failure "
        "is invoked to supply a corrected json_input before retrying."
    ),
    tasks=[get_stats, calculate_stats, llm_orchestration_on_failure],
    input_type=GetAndCalculateStatsInput,
    output_type=GetAndCalculateStatsOutput,
    pipeline_fn=_pipeline,
)

__all__ = ["get_and_calculate_stats"]
