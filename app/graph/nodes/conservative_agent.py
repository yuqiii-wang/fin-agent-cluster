"""Node: Conservative risk agent — capital preservation & downside-first analysis."""

import logging
from typing import Any

from app.graph.state import FinAnalysisState
from app.graph.nodes.common import get_llm, log_node_execution, NodeTimer
from app.prompts.conservative_agent import conservative_agent_prompt

logger = logging.getLogger(__name__)


async def conservative_risk_agent(state: FinAnalysisState) -> dict[str, Any]:
    """Assess the security from a conservative, risk-focused perspective.

    Emphasizes downside protection, tail risks, valuation concerns,
    and defensive positioning. Runs in parallel with aggressive_profit_agent.

    Args:
        state: Current graph state with all collected data.

    Returns:
        Dict with conservative_assessment and step log entry.
    """
    ticker = state.get("security_ticker", "")
    logger.info("[conservative_risk_agent] ticker=%s", ticker)
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
        "major_security": state.get("major_security", "SPY"),
        "fundamental_analysis": state.get("fundamental_analysis", ""),
        "technical_analysis": state.get("technical_analysis", ""),
        "news_summary": state.get("news_summary", ""),
        "market_data": state.get("market_data", ""),
    }

    timer = NodeTimer()
    with timer:
        resp = await llm.ainvoke(conservative_agent_prompt.invoke(prompt_input))

    content = resp.content
    output = {
        "conservative_assessment": content,
        "steps": [f"[conservative_risk_agent] ticker={ticker} output_len={len(content)}"],
    }
    await log_node_execution(
        state["thread_id"], "conservative_risk_agent",
        {"ticker": ticker},
        {"conservative_assessment_len": len(content)},
        timer.started_at, timer.elapsed_ms,
    )
    return output
