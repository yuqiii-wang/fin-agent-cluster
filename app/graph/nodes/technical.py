"""Node: Technical analyzer — moving averages, RSI, MACD signals."""

import logging
from typing import Any

from app.graph.state import FinAnalysisState
from app.graph.nodes.common import get_llm, log_node_execution, NodeTimer, get_cached_analysis, save_analysis_snapshot
from app.prompts.technical import technical_analysis_prompt

logger = logging.getLogger(__name__)


async def technical_analyzer(state: FinAnalysisState) -> dict[str, Any]:
    """Perform technical analysis based on collected market data.

    Args:
        state: Current graph state with security details and market_data.

    Returns:
        Dict with technical_analysis content and step log entry.
    """
    ticker = state.get("security_ticker", "")
    security_id = state.get("security_id")
    logger.info("[technical_analyzer] ticker=%s", ticker)

    # ── DB-first: return cached snapshot if fresh ──────────────────────
    cached = await get_cached_analysis(security_id, "technical_analyzer")
    if cached:
        logger.info("[technical_analyzer] cache hit for %s", ticker)
        return {
            "technical_analysis": cached,
            "steps": [f"[technical_analyzer] ticker={ticker} cache_hit=True"],
        }

    llm = get_llm()
    prompt_input = {
        "security_ticker": ticker,
        "security_name": state.get("security_name", ""),
        "market_data": state.get("market_data", ""),
        "query": state["query"],
    }

    timer = NodeTimer()
    with timer:
        resp = await llm.ainvoke(technical_analysis_prompt.invoke(prompt_input))

    content = resp.content
    output = {
        "technical_analysis": content,
        "steps": [f"[technical_analyzer] ticker={ticker} output_len={len(content)}"],
    }
    await save_analysis_snapshot(security_id, "technical_analyzer", content, {"ticker": ticker})
    await log_node_execution(
        state["thread_id"], "technical_analyzer",
        {"ticker": ticker},
        {"technical_analysis_len": len(content)},
        timer.started_at, timer.elapsed_ms,
    )
    return output
