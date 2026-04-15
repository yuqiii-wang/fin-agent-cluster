"""decision_maker — Node: analyses MarketDataOutput and writes a report to
``fin_strategies.reports``.

Topology::

    … → market_data_collector → decision_maker → END

Receives ``state["market_data_output"]`` (serialised :class:`MarketDataOutput`),
calls the LLM via the decision_maker prompt, parses the JSON response into a
:class:`DecisionReport`, persists a row in ``fin_strategies.reports``, and
stores the report JSON in ``state["report"]``.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from backend.graph.agents.decision_maker.models.output import DecisionReport
from backend.graph.agents.decision_maker.tasks.db_insert import run_db_insert
from backend.graph.agents.decision_maker.tasks.llm_infer import run_llm_infer
from backend.graph.agents.market_data.models.output import MarketDataOutput
from backend.graph.agents.task_keys import DM_DB_INSERT_REPORT, DM_LLM_INFER
from backend.graph.state import FinAnalysisState
from backend.graph.utils.execution_log import finish_node_execution, start_node_execution
from backend.graph.utils.task_stream import create_task

logger = logging.getLogger(__name__)


async def decision_maker(state: FinAnalysisState) -> dict:
    """Node: produce a trading decision report from collected market data.

    Reads ``state["market_data_output"]`` (a serialised :class:`MarketDataOutput`
    dict), builds the LLM prompt context, streams the LLM response, parses the
    JSON payload into a :class:`DecisionReport`, then persists a row in
    ``fin_strategies.reports``.

    Args:
        state: Current graph state; must contain ``market_data_output``,
               ``ticker``, and ``query``.

    Returns:
        Partial state update with ``report`` (serialised :class:`DecisionReport`
        JSON) and a ``steps`` log entry.
    """
    ticker: str = state.get("ticker") or ""
    query: str = state.get("query") or ""
    thread_id: str = state.get("thread_id") or ""

    logger.info("[decision_maker] ticker=%s thread=%s", ticker, thread_id)

    t0 = time.monotonic()
    started_at = datetime.now(timezone.utc)

    node_execution_id = await start_node_execution(
        thread_id,
        "decision_maker",
        {"ticker": ticker, "query": query},
        started_at,
    )

    # -- Reconstruct context from MarketDataOutput in state ---------------------
    mdo_dict: dict = state.get("market_data_output") or {}
    try:
        mdo = MarketDataOutput.model_validate(mdo_dict)
        market_data_context = "\n".join(mdo.to_context_lines())
    except Exception as exc:
        logger.warning("[decision_maker] MarketDataOutput parse failed: %s", exc)
        market_data_context = ""

    if not market_data_context:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        await finish_node_execution(node_execution_id, {"error": "no market data"}, elapsed_ms)
        return {
            "report": "",
            "steps": ["[decision_maker] no market data available; skipping"],
        }

    # -- LLM inference ---------------------------------------------------------
    llm_task_id = await create_task(
        thread_id, DM_LLM_INFER, node_execution_id
    )
    try:
        report: DecisionReport = await run_llm_infer(
            query, market_data_context, thread_id, node_execution_id, llm_task_id
        )
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        await finish_node_execution(node_execution_id, {"error": str(exc)}, elapsed_ms)
        return {
            "report": "",
            "steps": [f"[decision_maker] LLM failed: {exc}"],
        }

    # -- DB insert -------------------------------------------------------------
    db_task_id = await create_task(
        thread_id, DM_DB_INSERT_REPORT, node_execution_id
    )
    await run_db_insert(ticker, report, thread_id, db_task_id)

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    await finish_node_execution(node_execution_id, {"ticker": ticker}, elapsed_ms)

    return {
        "report": report.model_dump_json(),
        "steps": [
            f"[decision_maker] ticker={ticker!r} | elapsed_ms={elapsed_ms}"
        ],
    }
