"""Node: Report generator — synthesizes dual-perspective investment report with key metrics."""

import logging
from typing import Any

from app.graph.state import FinAnalysisState
from app.graph.nodes.common import get_llm, log_node_execution, NodeTimer
from app.prompts.report import report_generator_prompt

logger = logging.getLogger(__name__)


async def report_generator(state: FinAnalysisState) -> dict[str, Any]:
    """Generate final consolidated report from conservative and aggressive perspectives.

    Synthesizes both agent viewpoints, highlights key quantitative metrics,
    and produces consensus per-horizon outlook with parseable sentiment block.

    Args:
        state: Current graph state with both assessment perspectives.

    Returns:
        Dict with report content and step log entry.
    """
    ticker = state.get("security_ticker", "")
    logger.info("[report_generator] ticker=%s", ticker)
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
        "entity_description": state.get("entity_description", ""),
        "peers": peers_str,
        "major_security": state.get("major_security", "SPY"),
        "query": state["query"],
        "market_data": state.get("market_data", ""),
        "fundamental_analysis": state.get("fundamental_analysis", ""),
        "technical_analysis": state.get("technical_analysis", ""),
        "news_summary": state.get("news_summary", ""),
        "conservative_assessment": state.get("conservative_assessment", ""),
        "aggressive_assessment": state.get("aggressive_assessment", ""),
    }

    timer = NodeTimer()
    with timer:
        resp = await llm.ainvoke(report_generator_prompt.invoke(prompt_input))

    content = resp.content
    logger.info(
        "[report_generator] FINAL REPORT for %s (thread=%s):\n%s",
        ticker, state.get("thread_id", ""), content,
    )
    output = {
        "report": content,
        "steps": [f"[report_generator] ticker={ticker} output_len={len(content)}"],
    }
    await log_node_execution(
        state["thread_id"], "report_generator",
        {"ticker": ticker},
        {"report_len": len(content)},
        timer.started_at, timer.elapsed_ms,
    )
    return output
