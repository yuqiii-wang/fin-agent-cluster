"""Prompt builder for the stream_llm (conclusion node) path."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage


async def run_stream_async(
    thread_id: str,
    task_id: str,
    task_name: str,
    node_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Build the stream_llm prompt and delegate to ``run_stream_core``.

    Handles the ``stream_llm`` path which builds its own prompt from the
    merged research payload rather than using a registered builder.

    Args:
        thread_id:  LangGraph thread UUID.
        task_id:    Governance UUID of the owning ``fin_agents.tasks`` row.
        task_name:  Human label, e.g. ``"stream_llm"``.
        node_name:  Owning node name, e.g. ``"conclusion_node"``.
        payload:    Serialised ``ConclusionNodeInput`` dict.

    Returns:
        ``{"thinking": str | None, "answer": dict, "total_tokens": int, "latency_ms": int}``
        where ``answer`` has keys: summary, recommendation, confidence, key_points, risk_factors.
    """
    from .llm_selection import select_llm
    from .stream_core import run_stream_core

    query = payload.get("query", "")
    stats_analysis = payload.get("stats_analysis", "")
    stats_key_metrics = payload.get("stats_key_metrics", {})
    news_sentiment = payload.get("news_sentiment", "")
    news_highlights: list[str] = payload.get("news_highlights", [])

    highlights_text = "\n".join(f"- {h}" for h in news_highlights) if news_highlights else "No highlights."
    metrics_text = json.dumps(stats_key_metrics, indent=2) if stats_key_metrics else "N/A"

    system_content = (
        "You are a quantitative financial analyst. Produce structured investment conclusions "
        "based on market research. Respond ONLY with a JSON object (no markdown fences, no extra "
        "text) with exactly these fields:\n"
        '{"summary": "<2-3 sentence overall conclusion>", '
        '"recommendation": "<Buy|Sell|Hold>", '
        '"confidence": "<High|Medium|Low>", '
        '"key_points": ["<point1>", "<point2>", ...], '
        '"risk_factors": ["<risk1>", "<risk2>", ...]}'
    )
    human_content = (
        f"Query: {query}\n\n"
        f"Statistical Analysis:\n{stats_analysis or 'Not available.'}\n\n"
        f"Key Metrics:\n{metrics_text}\n\n"
        f"News Sentiment:\n{news_sentiment or 'Not available.'}\n\n"
        f"News Highlights:\n{highlights_text}"
    )
    messages = [SystemMessage(content=system_content), HumanMessage(content=human_content)]

    llm = select_llm(query)
    return await run_stream_core(thread_id, task_id, task_name, node_name, payload, messages, llm)
