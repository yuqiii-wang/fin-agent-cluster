"""Node: News collector — gathers and analyzes recent news sentiment."""

import logging
from typing import Any

from app.graph.state import FinAnalysisState
from app.graph.nodes.common import get_llm, log_node_execution, NodeTimer, get_cached_analysis, save_analysis_snapshot
from app.prompts.news import news_analysis_prompt
from app.quant_api.service import MarketDataService

logger = logging.getLogger(__name__)


async def news_collector(state: FinAnalysisState) -> dict[str, Any]:
    """Collect and analyze recent news sentiment for the security.

    Fetches real news headlines from the market data API
    (yfinance → FMP fallback) then passes them to the LLM for
    sentiment analysis.

    Args:
        state: Graph state with security details, peers, and market data.

    Returns:
        Dict with news_summary and step log entry.
    """
    ticker = state.get("security_ticker", "")
    security_id = state.get("security_id")
    logger.info("[news_collector] ticker=%s", ticker)

    # ── DB-first: return cached snapshot if fresh ──────────────────────
    cached = await get_cached_analysis(security_id, "news_collector")
    if cached:
        logger.info("[news_collector] cache hit for %s", ticker)
        return {
            "news_summary": cached,
            "steps": [f"[news_collector] ticker={ticker} cache_hit=True"],
        }

    llm = get_llm()
    peers = state.get("peers", {})
    peer_tickers = []
    for v in peers.values():
        if isinstance(v, list):
            peer_tickers.extend(v)
    peers_str = ", ".join(peer_tickers[:10]) if peer_tickers else "none identified"

    # Fetch real news headlines
    news_context = ""
    try:
        async with MarketDataService(
            thread_id=state.get("thread_id"), node_name="news_collector"
        ) as svc:
            news_context = await svc.fetch_news_context(ticker, limit=15)
    except Exception as exc:
        logger.warning("[news_collector] API fetch failed: %s", exc)

    prompt_input = {
        "security_ticker": ticker,
        "security_name": state.get("security_name", ""),
        "industry": state.get("industry", ""),
        "peers": peers_str,
        "market_data": state.get("market_data", "Not yet available"),
        "news_context": news_context or "(no recent news available)",
    }

    timer = NodeTimer()
    with timer:
        resp = await llm.ainvoke(news_analysis_prompt.invoke(prompt_input))

    content = resp.content
    output = {
        "news_summary": content,
        "steps": [f"[news_collector] output_len={len(content)}"],
    }
    await save_analysis_snapshot(security_id, "news_collector", content, {"ticker": ticker})

    await log_node_execution(
        state["thread_id"],
        "news_collector",
        {"ticker": ticker},
        {"news_summary_len": len(content)},
        timer.started_at,
        timer.elapsed_ms,
    )
    return output
