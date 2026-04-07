"""Node: Market data collector — gathers market data for the queried asset."""

import logging
from datetime import date, timedelta
from typing import Any

from app.graph.state import FinAnalysisState
from app.graph.nodes.common import get_llm, log_node_execution, NodeTimer, get_cached_analysis, save_analysis_snapshot
from app.prompts.market_data import market_data_prompt
from app.quant_api.service import MarketDataService

logger = logging.getLogger(__name__)


async def market_data_collector(state: FinAnalysisState) -> dict[str, Any]:
    """Collect market data for the queried asset using enriched context.

    Fetches real OHLCV and quote data from the market data API
    (yfinance → FMP fallback) then passes that context to the LLM
    for structured commentary.

    Args:
        state: Current graph state with security details and peer info.

    Returns:
        Dict with market_data content and step log entry.
    """
    ticker = state.get("security_ticker", "")
    security_id = state.get("security_id")
    logger.info("[market_data_collector] ticker=%s", ticker)
    llm = get_llm()

    # ── DB-first: return cached snapshot if fresh ──────────────────────
    cached = await get_cached_analysis(security_id, "market_data_collector")
    if cached:
        logger.info("[market_data_collector] cache hit for %s", ticker)
        return {
            "market_data": cached,
            "steps": [f"[market_data_collector] ticker={ticker} cache_hit=True"],
        }
    peers = state.get("peers", {})
    peer_tickers = []
    for v in peers.values():
        if isinstance(v, list):
            peer_tickers.extend(v)
    peers_str = ", ".join(peer_tickers[:10]) if peer_tickers else "none identified"

    # Fetch real price data (90 calendar days)
    to_date = date.today()
    from_date = to_date - timedelta(days=90)
    price_context = ""
    try:
        async with MarketDataService(
            thread_id=state.get("thread_id"), node_name="market_data_collector"
        ) as svc:
            price_context = await svc.fetch_price_context(ticker, from_date, to_date)
    except Exception as exc:
        logger.warning("[market_data_collector] API fetch failed: %s", exc)

    prompt_input = {
        "security_ticker": ticker,
        "security_name": state.get("security_name", ""),
        "industry": state.get("industry", ""),
        "peers": peers_str,
        "major_security": state.get("major_security", "SPY"),
        "query": state["query"],
        "price_context": price_context or "(no real-time price data available)",
    }

    timer = NodeTimer()
    with timer:
        resp = await llm.ainvoke(market_data_prompt.invoke(prompt_input))

    content = resp.content
    output = {
        "market_data": content,
        "steps": [f"[market_data_collector] ticker={ticker} output_len={len(content)}"],
    }
    await save_analysis_snapshot(security_id, "market_data_collector", content, {"ticker": ticker})
    await log_node_execution(
        state["thread_id"],
        "market_data_collector",
        {"ticker": ticker},
        {"market_data_len": len(content)},
        timer.started_at,
        timer.elapsed_ms,
    )
    return output
