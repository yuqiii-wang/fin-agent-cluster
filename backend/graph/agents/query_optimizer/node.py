"""query_optimizer — Node 0: resolves query context via a structured LangChain chain.

Runs before market_data_collector. Produces a :class:`QueryOptimizerOutput` with
two structured sections:

- ``quants``: ticker, peers, region, ticker index
- ``news``: all named search queries populated from static templates

Sequential tasks (delegated to :mod:`tasks` sub-package):
  1. :func:`~tasks.comprehend_basics` — stream raw JSON from LLM
  2. :func:`~tasks.validate_basics`   — correct region / index / industry against SQL static data
  3. :func:`~tasks.populate_json`     — build full output using static templates
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from backend.graph.state import FinAnalysisState
from backend.graph.utils.execution_log import start_node_execution, finish_node_execution
from backend.graph.agents.query_optimizer.chain import build_chain
from backend.graph.agents.query_optimizer.tasks import comprehend_basics, validate_basics, populate_json, populate_sec_profile
from backend.llm import get_active_provider, get_llm

logger = logging.getLogger(__name__)


async def query_optimizer(state: FinAnalysisState) -> dict:
    """Node 0: Parse user query and produce a validated :class:`QueryOptimizerOutput`.

    Streams JSON from the LLM chain, then builds the full output using static
    news query templates keyed on ticker, industry, and region.  Outputs a
    :class:`QueryOptimizerOutput` with ``quants`` and ``news`` sections for the
    downstream market_data_collector node.

    Args:
        state: Current graph state containing the raw ``query``.

    Returns:
        Partial state update with ``ticker``, ``peer_tickers``, ``ticker_indexes``,
        ``market_data_input`` (structured dict), and a ``steps`` log entry.
    """
    query: str = state["query"]
    logger.info("[query_optimizer] query=%s", query)

    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()
    thread_id: str = state.get("thread_id", "")  # type: ignore[assignment]

    _provider = get_active_provider()
    _llm = get_llm(temperature=0.1)
    _chain = await build_chain(_llm)

    node_execution_id = await start_node_execution(
        thread_id, "query_optimizer", {"query": query}, started_at
    )

    # ── Task 1: stream LLM JSON ──────────────────────────────────────────────
    raw_json = await comprehend_basics(_chain, query, thread_id, node_execution_id, _provider)
    if raw_json is None:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        await finish_node_execution(
            node_execution_id, {"error": "comprehend_basics failed"}, elapsed_ms
        )
        return {
            "steps": [f"[query_optimizer] input='{query}' | error=comprehend_basics failed"]
        }

    # ── Task 2: correct region / index / industry vs SQL static data ──────────
    validated_json = await validate_basics(raw_json, thread_id, node_execution_id, _provider)
    if validated_json is None:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        await finish_node_execution(
            node_execution_id, {"error": "validate_basics failed"}, elapsed_ms
        )
        return {
            "steps": [f"[query_optimizer] input='{query}' | error=validate_basics failed"]
        }

    # ── Task 3: build full QueryOptimizerOutput ──────────────────────────────
    result = await populate_json(validated_json, query, thread_id, node_execution_id)
    if result is None:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        await finish_node_execution(
            node_execution_id, {"error": "populate_json failed"}, elapsed_ms
        )
        return {
            "steps": [f"[query_optimizer] input='{query}' | error=populate_json failed"]
        }

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    # ── Task 4: ensure sec_profile exists for the resolved ticker ────────────
    await populate_sec_profile(
        ticker=result.quants.ticker,
        region=result.quants.region,
        security_name=result.quants.security_name,
        thread_id=thread_id,
        node_execution_id=node_execution_id,
        provider=_provider,
    )

    await finish_node_execution(
        node_execution_id,
        {
            "ticker": result.quants.ticker,
            "industry": result.quants.industry,
            "opposite_industry": result.quants.opposite_industry,
            "major_peers": result.quants.major_peers,
            "peer_tickers": result.quants.peer_tickers,
            "region": result.quants.region,
            "ticker_indexes": result.quants.ticker_indexes,
            "market_data_input": result.model_dump(),
        },
        elapsed_ms,
    )

    logger.info(
        "[query_optimizer] ticker=%s industry=%s peers=%s index=%s region=%s",
        result.quants.ticker, result.quants.industry, result.quants.peer_tickers,
        result.quants.ticker_indexes, result.quants.region,
    )

    return {
        "ticker": result.quants.ticker,
        "peer_tickers": result.quants.peer_tickers,
        "ticker_indexes": result.quants.ticker_indexes,
        "market_data_input": result.model_dump(),
        "steps": [
            f"[query_optimizer] ticker={result.quants.ticker!r} industry={result.quants.industry!r} "
            f"indexes={result.quants.ticker_indexes} region={result.quants.region!r} "
            f"peers={result.quants.peer_tickers} | elapsed_ms={elapsed_ms}"
        ],
    }

