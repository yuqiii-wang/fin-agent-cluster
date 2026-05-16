"""Regional analyze tasks — apac_analyze, emea_analyze, amer_analyze.

Each task shares the same Celery execution pattern but carries region-specific
knowledge about active exchanges and session context.

Execution layers (per task)
---------------------------
LangGraph layer (``@task``):
    Calls ``create_task``, delegates to Celery via ``delegate_completion``,
    and returns a ``TaskOutput``.

Celery layer (``_handler_*``):
    Pure async function with region-specific business logic.  Registered in
    ``HANDLERS`` and dispatched by the Celery completion worker.

Public exports
--------------
``apac_analyze``, ``emea_analyze``, ``amer_analyze`` — ``NodeTask`` instances.
``HANDLERS`` — flat dict ``{task_name: handler}`` for the Celery registry.
"""

from __future__ import annotations

import logging

from langgraph.func import task

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.nodes.base.models import TaskInput, TaskOutput
from backend.langgraph.nodes.base.task import NodeTask
from backend.langgraph.nodes.regional_analyze_nodes.models import (
    RegionalAnalyzeInput,
    RegionalAnalyzeOutput,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# APAC handler  — UTC 00:00-07:59
# ---------------------------------------------------------------------------

_APAC_EXCHANGES = ["TSE", "HKEX", "SSE", "SZSE", "SGX", "ASX"]
_EMEA_EXCHANGES = ["LSE", "Euronext", "Xetra", "SIX", "OMX"]
_AMER_EXCHANGES = ["NYSE", "NASDAQ", "TSX", "B3", "BMV"]


async def _handler_apac(payload: dict) -> dict:
    """Build APAC session context for the query.

    Args:
        payload: Serialised ``RegionalAnalyzeInput`` dict.

    Returns:
        Serialised ``RegionalAnalyzeOutput`` dict.
    """
    inp = RegionalAnalyzeInput.model_validate(payload)
    return RegionalAnalyzeOutput(
        region="apac",
        active_exchanges=_APAC_EXCHANGES,
        session_note=(
            "Asia-Pacific session (UTC 00:00-08:00): Tokyo, Hong Kong, Shanghai, "
            "Singapore, and Sydney exchanges are in primary trading hours."
        ),
        intent=inp.intent,
        symbols=inp.symbols,
    ).model_dump()


async def _handler_emea(payload: dict) -> dict:
    """Build EMEA session context for the query.

    Args:
        payload: Serialised ``RegionalAnalyzeInput`` dict.

    Returns:
        Serialised ``RegionalAnalyzeOutput`` dict.
    """
    inp = RegionalAnalyzeInput.model_validate(payload)
    return RegionalAnalyzeOutput(
        region="emea",
        active_exchanges=_EMEA_EXCHANGES,
        session_note=(
            "EMEA session (UTC 08:00-16:00): London, Euronext, Deutsche Börse, "
            "SIX Swiss, and OMX exchanges are in primary trading hours."
        ),
        intent=inp.intent,
        symbols=inp.symbols,
    ).model_dump()


async def _handler_amer(payload: dict) -> dict:
    """Build AMER session context for the query.

    Args:
        payload: Serialised ``RegionalAnalyzeInput`` dict.

    Returns:
        Serialised ``RegionalAnalyzeOutput`` dict.
    """
    inp = RegionalAnalyzeInput.model_validate(payload)
    return RegionalAnalyzeOutput(
        region="amer",
        active_exchanges=_AMER_EXCHANGES,
        session_note=(
            "Americas session (UTC 16:00-24:00): NYSE, NASDAQ, TSX, B3, and BMV "
            "exchanges are in primary trading hours."
        ),
        intent=inp.intent,
        symbols=inp.symbols,
    ).model_dump()


# ---------------------------------------------------------------------------
# LangGraph @task factory
# ---------------------------------------------------------------------------


def _make_regional_task_fn(task_name: str, handler_fn):
    """Return a @task-decorated coroutine bound to the given task name and handler."""

    @task
    async def _regional_task(
        task_input: TaskInput[RegionalAnalyzeInput],
    ) -> TaskOutput[RegionalAnalyzeOutput]:
        """LangGraph @task: delegates regional analysis to a Celery completion worker.

        Args:
            task_input: Typed envelope with TaskContext and RegionalAnalyzeInput content.

        Returns:
            TaskOutput wrapping the RegionalAnalyzeOutput from the Celery worker.
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
        output = RegionalAnalyzeOutput.model_validate(result)
        return TaskOutput(ctx=ctx, content=output)

    return _regional_task


# ---------------------------------------------------------------------------
# NodeTask instances
# ---------------------------------------------------------------------------

apac_analyze = NodeTask(
    name="apac_analyze",
    description=(
        "Analyze APAC session context (UTC 00:00-08:00): active exchanges, "
        "session note, and regional market framing for the query."
    ),
    input_type=RegionalAnalyzeInput,
    output_type=RegionalAnalyzeOutput,
    task_fn=_make_regional_task_fn("apac_analyze", _handler_apac),
    handler=_handler_apac,
)

emea_analyze = NodeTask(
    name="emea_analyze",
    description=(
        "Analyze EMEA session context (UTC 08:00-16:00): active exchanges, "
        "session note, and regional market framing for the query."
    ),
    input_type=RegionalAnalyzeInput,
    output_type=RegionalAnalyzeOutput,
    task_fn=_make_regional_task_fn("emea_analyze", _handler_emea),
    handler=_handler_emea,
)

amer_analyze = NodeTask(
    name="amer_analyze",
    description=(
        "Analyze AMER session context (UTC 16:00-24:00): active exchanges, "
        "session note, and regional market framing for the query."
    ),
    input_type=RegionalAnalyzeInput,
    output_type=RegionalAnalyzeOutput,
    task_fn=_make_regional_task_fn("amer_analyze", _handler_amer),
    handler=_handler_amer,
)

HANDLERS: dict = {
    apac_analyze.name: apac_analyze.handler,
    emea_analyze.name: emea_analyze.handler,
    amer_analyze.name: amer_analyze.handler,
}

__all__ = ["apac_analyze", "emea_analyze", "amer_analyze", "HANDLERS"]
