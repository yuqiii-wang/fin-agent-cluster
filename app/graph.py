"""
5-node LangGraph financial analysis workflow.

Nodes:
  1. market_data_collector  – Gathers market data for the queried asset
  2. fundamental_analyzer   – Evaluates fundamentals (PE, revenue, margins)
  3. technical_analyzer     – Performs technical analysis (moving averages, RSI)
  4. risk_assessor          – Synthesizes risk profile from both analyses
  5. report_generator       – Produces the final human-readable report

Graph edges (hybrid):
  START → market_data_collector ─→ fundamental_analyzer ─┐
                               ↘→ technical_analyzer  ──┴→ risk_assessor → report_generator → END

  market_data_collector runs first; fundamental_analyzer and technical_analyzer
  execute in parallel; risk_assessor fans back in once both complete.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Annotated, TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Shared LLM ──────────────────────────────────────────────────────────────
llm = ChatOpenAI(
    api_key=settings.ARK_API_KEY,
    base_url=settings.ARK_BASE_URL,
    model=settings.ARK_MODEL,
    temperature=0.3,
)


# ── Node execution logger ────────────────────────────────────────────────────
async def _log_node_execution(
    thread_id: str,
    node_name: str,
    input_data: dict,
    output_data: dict,
    started_at: datetime,
    elapsed_ms: int,
) -> None:
    """Persist a node's input/output and elapsed time to node_executions."""
    from app.database import _get_session_factory
    from app.models import NodeExecution

    factory = _get_session_factory()
    async with factory() as session:
        session.add(
            NodeExecution(
                thread_id=thread_id,
                node_name=node_name,
                input=input_data,
                output=output_data,
                started_at=started_at,
                elapsed_ms=elapsed_ms,
            )
        )
        await session.commit()


# ── State schema ─────────────────────────────────────────────────────────────
def _merge_lists(a: list[str], b: list[str]) -> list[str]:
    return a + b


class FinAnalysisState(TypedDict):
    query: str
    thread_id: str  # Correlation ID for logging
    market_data: str
    fundamental_analysis: str
    technical_analysis: str
    risk_assessment: str
    report: str
    # Accumulate step-by-step logs so every node's I/O is traceable
    steps: Annotated[list[str], _merge_lists]


# ── Node implementations ────────────────────────────────────────────────────
async def market_data_collector(state: FinAnalysisState) -> dict:
    """Node 1: Collect market data for the queried asset."""
    logger.info("[market_data_collector] query=%s", state["query"])
    prompt = (
        f"You are a financial data assistant. Given the user query: '{state['query']}', "
        "provide simulated but realistic market data including current price, "
        "52-week high/low, market cap, volume, and recent price changes. "
        "Format as a concise data summary. Respond in English."
    )
    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()
    resp = await llm.ainvoke(prompt)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    content = resp.content
    output = {
        "market_data": content,
        "steps": [f"[market_data_collector] input='{state['query']}' | output_len={len(content)}"],
    }
    await _log_node_execution(
        state["thread_id"], "market_data_collector",
        {"query": state["query"]},
        {"market_data": content},
        started_at, elapsed_ms,
    )
    return output


async def fundamental_analyzer(state: FinAnalysisState) -> dict:
    """Node 2: Analyze fundamentals based on market data."""
    logger.info("[fundamental_analyzer] running")
    prompt = (
        f"You are a fundamental analysis expert. Based on this market data:\n{state['market_data']}\n\n"
        f"For the query: '{state['query']}', provide fundamental analysis including "
        "P/E ratio assessment, revenue trends, profit margins, debt levels, and earnings outlook. "
        "Keep it concise with bullet points. Respond in English."
    )
    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()
    resp = await llm.ainvoke(prompt)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    content = resp.content
    output = {
        "fundamental_analysis": content,
        "steps": [f"[fundamental_analyzer] output_len={len(content)}"],
    }
    await _log_node_execution(
        state["thread_id"], "fundamental_analyzer",
        {"query": state["query"], "market_data": state["market_data"]},
        {"fundamental_analysis": content},
        started_at, elapsed_ms,
    )
    return output


async def technical_analyzer(state: FinAnalysisState) -> dict:
    """Node 3: Perform technical analysis."""
    logger.info("[technical_analyzer] running")
    prompt = (
        f"You are a technical analysis expert. Based on this market data:\n{state['market_data']}\n\n"
        f"For the query: '{state['query']}', provide technical analysis including "
        "moving averages (50-day, 200-day), RSI, MACD signals, support/resistance levels, "
        "and trend assessment. Keep it concise. Respond in English."
    )
    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()
    resp = await llm.ainvoke(prompt)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    content = resp.content
    output = {
        "technical_analysis": content,
        "steps": [f"[technical_analyzer] output_len={len(content)}"],
    }
    await _log_node_execution(
        state["thread_id"], "technical_analyzer",
        {"query": state["query"], "market_data": state["market_data"]},
        {"technical_analysis": content},
        started_at, elapsed_ms,
    )
    return output


async def risk_assessor(state: FinAnalysisState) -> dict:
    """Node 4: Assess risk combining fundamental + technical analysis."""
    logger.info("[risk_assessor] running")
    prompt = (
        "You are a risk assessment specialist. Based on:\n"
        f"Fundamental Analysis:\n{state['fundamental_analysis']}\n\n"
        f"Technical Analysis:\n{state['technical_analysis']}\n\n"
        "Provide a risk assessment including: overall risk level (Low/Medium/High), "
        "key risk factors, volatility assessment, and recommended position sizing. "
        "Respond in English."
    )
    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()
    resp = await llm.ainvoke(prompt)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    content = resp.content
    output = {
        "risk_assessment": content,
        "steps": [f"[risk_assessor] output_len={len(content)}"],
    }
    await _log_node_execution(
        state["thread_id"], "risk_assessor",
        {
            "fundamental_analysis": state["fundamental_analysis"],
            "technical_analysis": state["technical_analysis"],
        },
        {"risk_assessment": content},
        started_at, elapsed_ms,
    )
    return output


async def report_generator(state: FinAnalysisState) -> dict:
    """Node 5: Generate final consolidated report."""
    logger.info("[report_generator] running")
    prompt = (
        "You are a senior financial analyst. Compile a final investment report based on:\n\n"
        f"Query: {state['query']}\n\n"
        f"Market Data:\n{state['market_data']}\n\n"
        f"Fundamental Analysis:\n{state['fundamental_analysis']}\n\n"
        f"Technical Analysis:\n{state['technical_analysis']}\n\n"
        f"Risk Assessment:\n{state['risk_assessment']}\n\n"
        "Produce a clear, structured report with: Executive Summary, Key Findings, "
        "Recommendation (Buy/Hold/Sell), Target Price Range, and Risk Disclaimer. Respond in English."
    )
    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()
    resp = await llm.ainvoke(prompt)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    content = resp.content
    output = {
        "report": content,
        "steps": [f"[report_generator] output_len={len(content)}"],
    }
    await _log_node_execution(
        state["thread_id"], "report_generator",
        {
            "query": state["query"],
            "market_data": state["market_data"],
            "fundamental_analysis": state["fundamental_analysis"],
            "technical_analysis": state["technical_analysis"],
            "risk_assessment": state["risk_assessment"],
        },
        {"report": content},
        started_at, elapsed_ms,
    )
    return output


# ── Build graph ──────────────────────────────────────────────────────────────
def build_graph() -> StateGraph:
    """Construct the 5-node financial analysis graph (uncompiled).

    Hybrid topology:
      sequential → parallel fan-out → fan-in → sequential
    """
    builder = StateGraph(FinAnalysisState)

    builder.add_node("market_data_collector", market_data_collector)
    builder.add_node("fundamental_analyzer", fundamental_analyzer)
    builder.add_node("technical_analyzer", technical_analyzer)
    builder.add_node("risk_assessor", risk_assessor)
    builder.add_node("report_generator", report_generator)

    # Step 1 – sequential: collect market data first
    builder.add_edge(START, "market_data_collector")

    # Step 2 – parallel fan-out: run both analyzers concurrently
    builder.add_edge("market_data_collector", "fundamental_analyzer")
    builder.add_edge("market_data_collector", "technical_analyzer")

    # Step 3 – fan-in: risk_assessor waits for both analyzers
    builder.add_edge("fundamental_analyzer", "risk_assessor")
    builder.add_edge("technical_analyzer", "risk_assessor")

    # Step 4 – sequential: produce final report
    builder.add_edge("risk_assessor", "report_generator")
    builder.add_edge("report_generator", END)

    return builder
