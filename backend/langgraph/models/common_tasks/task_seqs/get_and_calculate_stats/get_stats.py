"""get_stats — common NodeTask to fetch market OHLCV stats and news from resource APIs.

Fetches OHLCV market data via :class:`~backend.resources.stats.client.StatsClient`
and recent news via :class:`~backend.resources.news.client.NewsClient` for a given
symbol and period.  The raw API response is cached in ``fin_markets.quant_raw`` with
a 4-hour TTL; subsequent calls within the TTL window are served from the DB cache
rather than making a new external request.

Direct injection paths
----------------------
When ``text_content`` or ``json_input`` is provided, the external API is bypassed.
Both paths store the caller-supplied data in ``quant_raw`` under a deterministic
cache key.  An optional ``src_task_id`` can be supplied to record which upstream
task produced the data; :func:`validate_src_reference` will then cross-check that
the injected payload traces back to that task's ``task_executions`` output.

Execution layers
----------------
LangGraph layer (``_get_stats_task`` decorated with ``@task``):
    Calls ``create_task(..., view_type="Stats")``, delegates to the Celery
    completion worker via ``delegate_completion``, and returns a ``TaskOutput``.
    On exception, calls ``complete_task(failed=True)`` to emit the failure SSE.

Celery layer (``_handler``):
    Dispatches to one of three sub-handlers from ``get_stats_utils``:
    1. ``handle_json_input``     — when ``json_input`` is provided.
    2. ``handle_text_input``     — when ``text_content`` is provided.
    3. ``handle_external_fetch`` — external API call with provider/period fallback.
    After dispatch, if ``src_task_id`` is set, calls ``validate_src_reference`` to
    confirm data provenance.

Public exports
--------------
``get_stats``     — ``NodeTask`` instance used by node task runners.
``HANDLERS``      — dict slice for registration in ``backend.langgraph.nodes.HANDLERS``.
"""

from __future__ import annotations

import logging

from langgraph.func import task
from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils import (
    get_stats_pg_cache,
    handle_external_fetch,
    handle_json_input,
    handle_text_input,
    validate_src_reference,
)
from backend.langgraph.models.models import NodeContext, TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask
from backend.resources.news.models import NewsArticle
from backend.resources.stats.models import StatsRecord

logger = logging.getLogger(__name__)

_TASK_NAME = "get_stats"



# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class GetStatsInput(BaseModel):
    """Input for the get_stats task.

    Attributes:
        symbol:                   Equity ticker symbol, e.g. ``'AAPL'``.
        period:                   Aggregation period: ``'1d'``, ``'1w'``, ``'1mo'``, ``'3mo'``, ``'1y'``, ``'2y'``.
        news_limit:               Maximum number of news articles to fetch.
        bypass_threshold_minutes: If the last raw-data fetch was within this many minutes,
                                  signal downstream tasks to bypass recomputation and read
                                  directly from the DB.  Defaults to 60 minutes.
        text_content:             Optional pre-fetched text content (e.g. Markdown from
                                  ``html_to_markdown``).  When provided, bypasses the
                                  external API call.
        json_input:               Optional structured JSON data (e.g. from ``run_sandbox``
                                  stdout).  When provided, bypasses the external API call.
        src_task_id:              Optional ``task_id`` of the upstream task that produced
                                  the injected data (``text_content`` or ``json_input``).
                                  When set, :func:`validate_src_reference` loads that
                                  task's ``task_executions`` output and cross-checks that
                                  the injected payload values can be traced back to it.
    """

    symbol: str = Field(description="Equity ticker symbol, e.g. 'AAPL'.")
    period: str = Field(description="Aggregation period: '1d', '1w', '1mo', '3mo', '1y', '2y'.")
    news_limit: int = Field(default=10, ge=1, le=50, description="Max news articles to fetch.")
    bypass_threshold_minutes: int = Field(
        default=60, ge=1, description="Minutes within which downstream stats recomputation is skipped."
    )
    text_content: str | None = Field(
        default=None,
        description=(
            "Optional pre-fetched text content (e.g. Markdown from html_to_markdown). "
            "When provided, bypasses the external API call and stores the text "
            "directly in quant_raw with source='web_content', method='text_input'."
        ),
    )
    json_input: dict | None = Field(
        default=None,
        description=(
            "Optional structured JSON data (e.g. from run_sandbox stdout). "
            "When provided, bypasses the external API call and stores the dict "
            "directly in quant_raw with source='sandbox', method='json_input'."
        ),
    )
    src_task_id: str | None = Field(
        default=None,
        description=(
            "Optional task_id of the upstream task that produced the injected data "
            "(text_content or json_input). When set, validate_src_reference loads that "
            "task's output from fin_agents.task_executions and cross-checks that the "
            "injected payload values can be traced back to it."
        ),
    )


class GetStatsOutput(BaseModel):
    """Output from the get_stats task.

    Attributes:
        stats_record:      Fetched OHLCV stats record from the provider.
        news_articles:     Recent news articles for the symbol.
        from_cache:        ``True`` when the stats record was served from ``quant_raw`` cache.
        bypass_calculate:  ``True`` when the cached entry is fresh enough AND ``quant_stats``
                           already contains rows for the symbol/granularity, indicating that
                           downstream tasks (``calculate_stats``) can safely skip recomputation.
    """

    stats_record: StatsRecord
    news_articles: list[NewsArticle]
    from_cache: bool = Field(default=False)
    bypass_calculate: bool = Field(default=False)


# ---------------------------------------------------------------------------
# Celery layer — dispatcher
# ---------------------------------------------------------------------------


async def _handler(payload: dict) -> dict:
    """Dispatch get_stats to the appropriate sub-handler.

    Delegates to one of three sub-handlers from ``get_stats_utils`` based on
    whether the input carries injected data or requires an external fetch.
    When ``src_task_id`` is set, validates data provenance after dispatch.

    Args:
        payload: Serialised :class:`GetStatsInput` dict.

    Returns:
        Serialised :class:`GetStatsOutput` dict.
    """
    inp = GetStatsInput.model_validate(payload)

    if inp.json_input is not None:
        result = await handle_json_input(inp)
        if inp.src_task_id:
            await validate_src_reference(
                inp.src_task_id, injected_json=inp.json_input
            )
        return result

    if inp.text_content:
        result = await handle_text_input(inp)
        if inp.src_task_id:
            await validate_src_reference(
                inp.src_task_id, injected_text=inp.text_content
            )
        return result

    return await handle_external_fetch(inp)


# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------


@task
async def _get_stats_task(
    task_input: TaskInput[GetStatsInput],
) -> TaskOutput[GetStatsOutput]:
    """LangGraph @task: delegates get_stats to the Celery completion worker.

    Args:
        task_input: Typed envelope with :class:`~backend.langgraph.models.models.TaskContext`
                    and :class:`GetStatsInput` content.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`GetStatsOutput` from the Celery worker.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump()

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type="Stats",
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

get_stats = NodeTask(
    name=_TASK_NAME,
    description=(
        "Fetch OHLCV market statistics and recent news for an equity symbol from the "
        "configured stats provider (mock / yfinance / fmp).  Raw API responses are cached "
        "in fin_markets.quant_raw for 4 hours.  "
        "When json_input is provided it must include 'data_type' ('ohlcv', 'options', or "
        "'fundamentals') with the required fields for that type; invalid payloads raise "
        "immediately so llm_orchestration can supply a corrected json_input.  "
        "When src_task_id is also provided, validate_src_reference cross-checks the "
        "injected payload against the named task's output in fin_agents.task_executions."
    ),
    input_type=GetStatsInput,
    output_type=GetStatsOutput,
    task_fn=_get_stats_task,
    handler=_handler,
    pg_cache_fn=get_stats_pg_cache,
    is_required_llm_orchestration=True,
)

HANDLERS: dict = {_TASK_NAME: _handler}

__all__ = ["get_stats", "GetStatsInput", "GetStatsOutput", "HANDLERS"]
