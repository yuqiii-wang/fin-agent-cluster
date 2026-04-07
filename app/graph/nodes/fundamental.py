"""Node: Fundamental analyzer — evaluates fundamentals (PE, revenue, margins)."""

import logging
from typing import Any

from app.graph.state import FinAnalysisState
from app.graph.nodes.common import get_llm, log_node_execution, NodeTimer, get_cached_analysis, save_analysis_snapshot
from app.prompts.fundamental import fundamental_analysis_prompt
from app.quant_api.service import MarketDataService

logger = logging.getLogger(__name__)


async def fundamental_analyzer(state: FinAnalysisState) -> dict[str, Any]:
    """Analyze fundamentals based on real API data and entity info.

    Fetches key metrics and ratios from the market data API
    (yfinance → FMP fallback) then passes that context to the LLM
    for fundamental analysis.

    Args:
        state: Current graph state with security details, entity info, and market data.

    Returns:
        Dict with fundamental_analysis content and step log entry.
    """
    ticker = state.get("security_ticker", "")
    security_id = state.get("security_id")
    logger.info("[fundamental_analyzer] ticker=%s", ticker)
    llm = get_llm()

    # ── DB-first: return cached snapshot if fresh ──────────────────────
    cached = await get_cached_analysis(security_id, "fundamental_analyzer")
    if cached:
        logger.info("[fundamental_analyzer] cache hit for %s", ticker)
        return {
            "fundamental_analysis": cached,
            "steps": [f"[fundamental_analyzer] ticker={ticker} cache_hit=True"],
        }

    fundamentals_context = ""
    try:
        async with MarketDataService(
            thread_id=state.get("thread_id"), node_name="fundamental_analyzer"
        ) as svc:
            fundamentals_context = await svc.fetch_fundamentals_context(ticker)
    except Exception as exc:
        logger.warning("[fundamental_analyzer] API fetch failed: %s", exc)

    prompt_input = {
        "security_ticker": ticker,
        "security_name": state.get("security_name", ""),
        "industry": state.get("industry", ""),
        "entity_description": state.get("entity_description", ""),
        "market_data": state.get("market_data", ""),
        "fundamentals_context": fundamentals_context or "(no fundamental data available)",
        "query": state["query"],
    }

    timer = NodeTimer()
    with timer:
        resp = await llm.ainvoke(fundamental_analysis_prompt.invoke(prompt_input))

    content = resp.content
    output = {
        "fundamental_analysis": content,
        "steps": [f"[fundamental_analyzer] ticker={ticker} output_len={len(content)}"],
    }
    await save_analysis_snapshot(security_id, "fundamental_analyzer", content, {"ticker": ticker})
    await log_node_execution(
        state["thread_id"], "fundamental_analyzer",
        {"ticker": ticker},
        {"fundamental_analysis_len": len(content)},
        timer.started_at, timer.elapsed_ms,
    )
    return output
