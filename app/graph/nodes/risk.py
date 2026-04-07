"""Node: Risk assessor — synthesizes risk profile from all analyses."""

import logging
from typing import Any

from app.graph.state import FinAnalysisState
from app.graph.nodes.common import get_llm, log_node_execution, NodeTimer, get_cached_analysis, save_analysis_snapshot
from app.prompts.risk import risk_assessment_prompt

logger = logging.getLogger(__name__)


async def risk_assessor(state: FinAnalysisState) -> dict[str, Any]:
    """Assess risk combining fundamental, technical, and news analysis.

    Args:
        state: Current graph state with all analysis results.

    Returns:
        Dict with risk_assessment content and step log entry.
    """
    ticker = state.get("security_ticker", "")
    security_id = state.get("security_id")
    logger.info("[risk_assessor] ticker=%s", ticker)

    # ── DB-first: return cached snapshot if fresh ──────────────────────
    cached = await get_cached_analysis(security_id, "risk_assessor")
    if cached:
        logger.info("[risk_assessor] cache hit for %s", ticker)
        return {
            "risk_assessment": cached,
            "steps": [f"[risk_assessor] ticker={ticker} cache_hit=True"],
        }

    llm = get_llm()

    peers = state.get("peers", {})
    peer_tickers = []
    for v in peers.values():
        if isinstance(v, list):
            peer_tickers.extend(v)
    peers_str = ", ".join(peer_tickers[:10]) if peer_tickers else "none"

    prompt_input = {
        "security_ticker": ticker,
        "security_name": state.get("security_name", ""),
        "industry": state.get("industry", ""),
        "peers": peers_str,
        "opposite_industry": state.get("opposite_industry", ""),
        "fundamental_analysis": state.get("fundamental_analysis", ""),
        "technical_analysis": state.get("technical_analysis", ""),
        "news_summary": state.get("news_summary", ""),
    }

    timer = NodeTimer()
    with timer:
        resp = await llm.ainvoke(risk_assessment_prompt.invoke(prompt_input))

    content = resp.content
    output = {
        "risk_assessment": content,
        "steps": [f"[risk_assessor] ticker={ticker} output_len={len(content)}"],
    }
    await save_analysis_snapshot(security_id, "risk_assessor", content, {"ticker": ticker})
    await log_node_execution(
        state["thread_id"], "risk_assessor",
        {"ticker": ticker},
        {"risk_assessment_len": len(content)},
        timer.started_at, timer.elapsed_ms,
    )
    return output
