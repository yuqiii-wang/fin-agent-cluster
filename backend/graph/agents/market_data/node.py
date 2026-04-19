"""market_data_collector — Node 1: gathers market data for the queried asset.

Receives a :class:`QueryOptimizerOutput` from query_optimizer and delegates data
collection to two sub-pipelines:

Quant pipeline (uses ``market_data_input.quants``):
- Current price quote
- OHLCV bars: 4 windows (15min/1h/1day/1mo)
- Peer ticker quotes
- Macro commodity / rate OHLCV (gold, crude oil, natural gas, SOFR ON/TN/1M)
- US Bond yield curve

News pipeline (uses ``market_data_input.news``):
- Company news (yfinance, last 7 days)
- All named news search queries (company, macro, sector, global, etc.)

Each sub-task follows the DB-first pattern: check for fresh cached data,
fetch online only when absent or stale, and persist new data to the DB.

The node stores the structured :class:`MarketDataOutput` in state as
``market_data_output`` (serialised dict) for the downstream ``decision_maker``
node.  No LLM synthesis is performed here.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from backend.graph.state import FinAnalysisState
from backend.graph.utils.execution_log import start_node_execution, finish_node_execution
from backend.graph.utils.ohlcv import upsert_quant_stats
from backend.sse_notifications import create_task, complete_task, fail_task
from backend.graph.agents.task_keys import (
    MD_BOND,
    md_ohlcv,
    md_peer_ohlcv,
    md_index_ohlcv,
    md_macro,
    md_web_search,
)
from backend.graph.agents.query_optimizer.models import NewsContext, QuantContext, QueryOptimizerOutput
from backend.graph.agents.market_data.models.quant import (
    OHLCVWindowResult,
    MacroResult,
    BondResult,
    QuantCollectionResult,
)
from backend.resource_api.quant_api.constants import AUX_DAILY_WINDOW, INDEX_LABEL_TICKER_MAP
from backend.graph.agents.market_data.models.news import (
    NewsRawResults,
)
from backend.graph.agents.market_data.models.output import MarketDataOutput
from backend.graph.agents.market_data.tasks.news.web_search import run_web_search
from backend.graph.agents.market_data.tasks.quant.window import fetch_window
from backend.graph.agents.market_data.tasks.quant.macro import (
    fetch_macro_ticker,
    fetch_bond_yields,
    MACRO_SYMBOLS,
)
from backend.resource_api.quant_api.constants import OHLCV_WINDOWS as _WINDOWS
from backend.resource_api.quant_api.client import QuantClient
from backend.resource_api.news_api.client import NewsClient

logger = logging.getLogger(__name__)

_OHLCV_LABELS: dict[str, str] = {
    "15min": "15-min bars (last week)",
    "1h":    "1-hour bars (last month)",
    "1day":  "Daily bars (last year)",
    "1mo":   "Monthly bars (up to 10 years)",
}


def _candlestick_output(bars: list, source: str, symbol: str = "") -> dict:
    """Convert a list of OHLCVBar objects into a candlestick chart matrix payload.

    Returns a dict with ``chart_type``, ``symbol``, ``source``, ``dates``, and
    ``ohlcv`` (each row: ``[open, high, low, close, volume]``).
    """
    return {
        "chart_type": "candlestick",
        "symbol": symbol.upper() if symbol else "",
        "source": source,
        "dates": [b.date for b in bars],
        "ohlcv": [[b.open, b.high, b.low, b.close, b.volume] for b in bars],
    }


async def market_data_collector(state: FinAnalysisState) -> dict:
    """Node: Collect market data for the queried asset.

    Reads ``QueryOptimizerOutput`` from state, splits into quant and news pipelines,
    spawns parallel sub-tasks, then stores the structured :class:`MarketDataOutput`
    in ``state["market_data_output"]`` for the downstream ``decision_maker`` node.

    Args:
        state: Current graph state containing ``market_data_input`` from
               query_optimizer and the raw ``query`` string.

    Returns:
        Partial state update with ``ticker``, ``market_data_output`` (serialised
        dict), and a ``steps`` log entry.
    """
    logger.info("[market_data_collector] query=%s", state["query"])

    # -- Parse QueryOptimizerOutput from state -------------------------------------
    mdi: dict = state.get("market_data_input") or {}  # type: ignore[assignment]

    qoo: Optional[QueryOptimizerOutput] = None
    try:
        if mdi:
            qoo = QueryOptimizerOutput.model_validate(mdi)
    except Exception as exc:
        logger.warning("[market_data_collector] QueryOptimizerOutput parse failed: %s", exc)

    quants: Optional[QuantContext] = qoo.quants if qoo else None
    news_ctx: Optional[NewsContext] = qoo.news if qoo else None

    ticker: str = (quants.ticker if quants else "") or state.get("ticker") or ""  # type: ignore[assignment]
    peer_tickers: list[str] = (
        (quants.peer_tickers if quants else None) or state.get("peer_tickers") or []  # type: ignore[assignment]
    )
    ticker_indexes: list[str] = (quants.ticker_indexes if quants else None) or state.get("ticker_indexes") or []  # type: ignore[assignment]
    region: str = (quants.region if quants else "") or ""

    # Build news queries from NewsContext — include all non-empty fields
    news_queries: dict[str, str] = {}
    if news_ctx:
        news_queries = {k: v for k, v in news_ctx.model_dump().items() if v}

    thread_id: str = state.get("thread_id") or ""  # type: ignore[assignment]

    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()

    node_execution_id = await start_node_execution(
        thread_id,
        "market_data_collector",
        {"query": state["query"], "market_data_input": mdi},
        started_at,
    )

    if not ticker:
        elapsed = int((time.monotonic() - t0) * 1000)
        await finish_node_execution(node_execution_id, {"error": "no ticker resolved"}, elapsed)
        return {
            "market_data": "",
            "steps": ["[market_data_collector] no ticker resolved; skipping data fetch"],
        }

    qclient = QuantClient()
    nclient = NewsClient()

    # -- Pre-register task IDs for news sub-tasks --------------------------------
    _news_task_ids: dict[str, int] = {}
    for key in news_queries:
        tid = await create_task(thread_id, md_web_search(key), node_execution_id)
        _news_task_ids[key] = tid

    # ---------------------------------------------------------------------------
    # Quant sub-task coroutines
    # ---------------------------------------------------------------------------

    async def _run_ohlcv_window(window: object) -> OHLCVWindowResult:  # type: ignore[type-arg]
        """Fetch one OHLCV window; check DB coverage first; persist and return result."""
        task_key = md_ohlcv(window.granularity)  # type: ignore[attr-defined]
        task_id = await create_task(thread_id, task_key, node_execution_id)
        label = _OHLCV_LABELS[window.granularity]  # type: ignore[attr-defined,index]
        try:
            bars, actual_source = await fetch_window(
                qclient, ticker, window, thread_id, region=region or None  # type: ignore[arg-type]
            )
            if bars:
                await upsert_quant_stats(
                    bar_lists=[bars], symbol=ticker, source=actual_source,
                    interval=window.interval, region=region or None,  # type: ignore[attr-defined]
                )
            await complete_task(
                thread_id, task_id, task_key,
                _candlestick_output(bars, actual_source, ticker),
            )
            return OHLCVWindowResult(
                ticker=ticker,
                window=window.granularity,  # type: ignore[attr-defined]
                label=label,
                bars=[b.model_dump() for b in bars],
                source=actual_source,
            )
        except Exception as exc:
            logger.warning("[market_data_collector] OHLCV %s failed: %s", window.granularity, exc)  # type: ignore[attr-defined]
            await fail_task(thread_id, task_id, task_key, str(exc))
            return OHLCVWindowResult(ticker=ticker, window=window.granularity, label=label, error=str(exc))  # type: ignore[attr-defined]

    async def _run_peer_ohlcv(peer: str) -> OHLCVWindowResult:
        """Fetch 1-year daily OHLCV for a peer ticker."""
        task_key = md_peer_ohlcv(peer)
        task_id = await create_task(thread_id, task_key, node_execution_id)
        try:
            bars, actual_source = await fetch_window(qclient, peer, AUX_DAILY_WINDOW, thread_id, region=region or None)
            if bars:
                await upsert_quant_stats(bar_lists=[bars], symbol=peer, source=actual_source, interval="1d", region=region or None)
            await complete_task(thread_id, task_id, task_key, _candlestick_output(bars, actual_source, peer))
            return OHLCVWindowResult(ticker=peer, window="1day", label=f"{peer} 2y daily", bars=[b.model_dump() for b in bars], source=actual_source)
        except Exception as exc:
            logger.warning("[market_data_collector] peer OHLCV %s failed: %s", peer, exc)
            await fail_task(thread_id, task_id, task_key, str(exc))
            return OHLCVWindowResult(ticker=peer, window="1day", label=f"{peer} 2y daily", error=str(exc))

    async def _run_index_ohlcv(label_key: str) -> OHLCVWindowResult:
        """Fetch 1-year daily OHLCV for one benchmark index.

        ``label_key`` is the human-readable keyword from ``fin_markets.regions.indexes``
        (e.g. ``'NASDAQ_100'``, ``'S&P_500'``).  The canonical ticker is resolved
        via ``INDEX_LABEL_TICKER_MAP`` before passing to the quant provider.
        """
        task_key = md_index_ohlcv(label_key)
        task_id = await create_task(thread_id, task_key, node_execution_id)
        ticker_sym = INDEX_LABEL_TICKER_MAP.get(label_key, label_key)
        try:
            bars, actual_source = await fetch_window(qclient, ticker_sym, AUX_DAILY_WINDOW, thread_id, region=region or None)
            if bars:
                await upsert_quant_stats(bar_lists=[bars], symbol=ticker_sym, source=actual_source, interval="1d", region=region or None)
            await complete_task(thread_id, task_id, task_key, _candlestick_output(bars, actual_source, ticker_sym))
            return OHLCVWindowResult(ticker=ticker_sym, window="1day", label=f"{label_key} index 2y daily", bars=[b.model_dump() for b in bars], source=actual_source)
        except Exception as exc:
            logger.warning("[market_data_collector] index OHLCV %s (%s) failed: %s", label_key, ticker_sym, exc)
            await fail_task(thread_id, task_id, task_key, str(exc))
            return OHLCVWindowResult(ticker=ticker_sym, window="1day", label=f"{label_key} index 2y daily", error=str(exc))

    async def _run_macro_quant(macro_key: str) -> MacroResult:
        """Fetch daily OHLCV for a macro commodity or rate index via QuantClient."""
        symbol, label = MACRO_SYMBOLS[macro_key]
        task_key = md_macro(macro_key)
        task_id = await create_task(
            thread_id, task_key, node_execution_id
        )
        try:
            result = await fetch_macro_ticker(qclient, symbol, label, thread_id, key=macro_key, region=region or None)
            chart_out = (
                _candlestick_output(result.bars, result.source)
                if result.bars
                else {"symbol": symbol, "bars_count": result.bars_count, "source": result.source}
            )
            await complete_task(
                thread_id, task_id, task_key,
                chart_out,
            )
            return result
        except Exception as exc:
            logger.warning("[market_data_collector] macro %s failed: %s", macro_key, exc)
            await fail_task(thread_id, task_id, task_key, str(exc))
            return MacroResult(key=macro_key, symbol=symbol, label=label, error=str(exc))

    async def _run_bond_yields() -> BondResult:
        """Fetch US Bond yield curve (1-month, 6-month, 5-year, 10-year) via QuantClient."""
        task_id = await create_task(
            thread_id, MD_BOND, node_execution_id
        )
        try:
            result = await fetch_bond_yields(qclient, thread_id, region=region or None)
            await complete_task(
                thread_id, task_id, MD_BOND,
                {"tenors_count": len(result.tenors)},
            )
            return result
        except Exception as exc:
            logger.warning("[market_data_collector] US Bond yields failed: %s", exc)
            await fail_task(thread_id, task_id, MD_BOND, str(exc))
            return BondResult(error=str(exc))

    # ---------------------------------------------------------------------------
    # Gather all sub-tasks concurrently
    # ---------------------------------------------------------------------------
    _MACRO_KEYS = list(MACRO_SYMBOLS.keys())
    n_ohlcv = len(_WINDOWS)
    n_news = len(news_queries)
    n_peer = len(peer_tickers)
    n_macro = len(_MACRO_KEYS)
    n_index = len(ticker_indexes)

    all_coros = (
        [_run_ohlcv_window(w) for w in _WINDOWS]
        + [
            run_web_search(nclient, ticker, label, q, _news_task_ids[label], thread_id)
            for label, q in news_queries.items()
        ]
        + [_run_peer_ohlcv(p) for p in peer_tickers]
        + [_run_macro_quant(k) for k in _MACRO_KEYS]
        + [_run_bond_yields()]
        + [_run_index_ohlcv(idx) for idx in ticker_indexes]
    )
    results: tuple = await asyncio.gather(*all_coros)

    # Unpack results by known index ranges into typed models
    ohlcv_results: list[OHLCVWindowResult] = list(results[:n_ohlcv])

    idx_after_news = n_ohlcv + n_news
    web_search_results: list[NewsRawResults] = list(results[n_ohlcv:idx_after_news])

    idx_after_peer = idx_after_news + n_peer
    peer_ohlcv_results: list[OHLCVWindowResult] = list(results[idx_after_news:idx_after_peer])

    idx_after_macros = idx_after_peer + n_macro
    macro_results: list[MacroResult] = list(results[idx_after_peer:idx_after_macros])
    bond_result: BondResult = results[idx_after_macros]
    index_ohlcv_results: list[OHLCVWindowResult] = list(results[idx_after_macros + 1 : idx_after_macros + 1 + n_index])

    # Build structured output
    mdo = MarketDataOutput(
        ticker=ticker,
        query=state["query"],
        quant=QuantCollectionResult(
            ohlcv_windows=ohlcv_results,
            peer_ohlcv=peer_ohlcv_results,
            index_ohlcv=index_ohlcv_results,
            macro=macro_results,
            bond=bond_result,
        ),
        news=web_search_results,
    )

    real_data_context = "\n".join(mdo.to_context_lines())
    logger.info(
        "[market_data_collector] assembled context for %s (%d chars)", ticker, len(real_data_context)
    )

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    mdo_dict = mdo.model_dump()
    await finish_node_execution(node_execution_id, {"ticker": ticker, "context_chars": len(real_data_context)}, elapsed_ms)

    return {
        "ticker": ticker,
        "market_data_output": mdo_dict,
        "steps": [
            f"[market_data_collector] ticker={ticker!r} region={region!r} "
            f"news_queries={n_news} peers={n_peer} | elapsed_ms={elapsed_ms}"
        ],
    }
