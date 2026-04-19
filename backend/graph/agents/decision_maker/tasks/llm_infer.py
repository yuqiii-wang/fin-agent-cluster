"""LLM inference task for the decision_maker node.

Calls the decision_maker prompt, streams the response, and parses the
JSON payload into a :class:`~backend.graph.agents.decision_maker.models.output.DecisionReport`.
"""

from __future__ import annotations

import json
import logging
import re

from langchain_core.output_parsers import StrOutputParser

from backend.graph.agents.decision_maker.models.output import DecisionReport
from backend.graph.agents.task_keys import DM_LLM_INFER
from backend.graph.prompts.decision_maker import build_prompt_template
from backend.sse_notifications import (
    TaskCancelledSignal,
    TaskPassSignal,
    cancel_task,
    complete_task,
    fail_task,
    stream_text_task,
)
from backend.llm import get_active_provider, get_llm

logger = logging.getLogger(__name__)


async def run_llm_infer(
    query: str,
    market_data_context: str,
    thread_id: str,
    node_execution_id: int | None,
    task_id: int,
) -> DecisionReport:
    """Stream the decision LLM and parse the JSON response.

    Args:
        query:               Original user query.
        market_data_context: Pre-formatted market data string from :class:`MarketDataOutput`.
        thread_id:           LangGraph thread UUID.
        node_execution_id:   FK to the parent ``node_executions`` row.
        task_id:             Pre-created ``fin_agents.tasks`` row ID.

    Returns:
        A :class:`DecisionReport` parsed from the LLM JSON response.
        Falls back to an empty :class:`DecisionReport` on parse failure.

    Raises:
        Exception: Re-raises LLM errors after recording the task failure.
    """
    _provider = get_active_provider()
    _llm = get_llm(temperature=0.2)
    _chain = build_prompt_template() | _llm | StrOutputParser()

    try:
        raw_json: str = await stream_text_task(
            thread_id,
            task_id,
            DM_LLM_INFER,
            _chain.astream({"query": query, "market_data_context": market_data_context}),
        )
        await complete_task(
            thread_id, task_id, DM_LLM_INFER, {"chars": len(raw_json), "text": raw_json}
        )
    except TaskCancelledSignal:
        logger.info("[decision_maker/llm_infer] LLM cancelled task_id=%d", task_id)
        await cancel_task(thread_id, task_id, DM_LLM_INFER)
        return DecisionReport()
    except TaskPassSignal as sig:
        logger.info("[decision_maker/llm_infer] LLM passed task_id=%d chars=%d", task_id, len(sig.partial_text))
        raw_json = sig.partial_text
        await complete_task(thread_id, task_id, DM_LLM_INFER, {"chars": len(raw_json), "text": raw_json, "passed": True})
    except Exception as exc:
        logger.warning("[decision_maker/llm_infer] LLM call failed: %s", exc)
        await fail_task(thread_id, task_id, DM_LLM_INFER, str(exc))
        raise

    # Strip <think>...</think> reasoning blocks and optional markdown fences
    cleaned = re.sub(r"<think>.*?</think>", "", raw_json, flags=re.DOTALL).strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        data = json.loads(cleaned)
        return DecisionReport.model_validate(data)
    except Exception as exc:
        logger.warning("[decision_maker/llm_infer] JSON parse failed: %s — using empty report", exc)
        return DecisionReport()
