"""Task 2 — populate_json: validate LLM basics and build full QueryOptimizerOutput.

Input:  raw_json (str), query (str), thread_id, node_execution_id
Output: QueryOptimizerOutput, or None on failure
"""

from __future__ import annotations

import logging
from typing import Optional

from backend.graph.agents.query_optimizer.models import (
    LLMRawContext,
    NewsContext,
    QuantContext,
    QueryOptimizerOutput,
)
from backend.graph.agents.task_keys import QO_POPULATE_JSON
from backend.graph.utils.task_stream import complete_task, create_task, fail_task

logger = logging.getLogger(__name__)


async def populate_json(
    raw_json: str,
    query: str,
    thread_id: str,
    node_execution_id: int,
) -> Optional[QueryOptimizerOutput]:
    """Validate LLM basics and populate full output using static templates.

    Parses the raw JSON via :class:`LLMRawContext`, builds :class:`QuantContext`
    from the core identity fields, and builds :class:`NewsContext` from static
    query templates keyed on ticker, security name, industry, and region.

    Args:
        raw_json:          Raw JSON string from the LLM (Task 1 output).
        query:             Original user query for the output ``query`` field.
        thread_id:         LangGraph thread id.
        node_execution_id: Parent node-execution id for task tracking.

    Returns:
        :class:`QueryOptimizerOutput` on success, or ``None`` on failure.
    """
    task_id = await create_task(
        thread_id, QO_POPULATE_JSON, node_execution_id
    )
    try:
        llm_ctx = LLMRawContext.model_validate_json(raw_json)
        result = QueryOptimizerOutput(
            query=query,
            quants=QuantContext.model_validate(llm_ctx.model_dump()),
            news=NewsContext.from_basics(
                ticker=llm_ctx.ticker,
                security_name=llm_ctx.security_name,
                industry=llm_ctx.industry,
                region=llm_ctx.region,
            ),
        )
        await complete_task(
            thread_id, task_id, QO_POPULATE_JSON,
            {"ticker": result.quants.ticker, "peers": result.quants.peer_tickers},
        )
        return result
    except Exception as exc:
        logger.warning("[query_optimizer] populate_json failed: %s", exc)
        await fail_task(
            thread_id, task_id, QO_POPULATE_JSON, str(exc)
        )
        return None
