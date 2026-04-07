"""Node 0: Query understanding — parses raw user query into structured financial intent."""

import json
import logging
from typing import Any

from app.graph.state import FinAnalysisState
from app.graph.nodes.common import get_llm, log_node_execution, NodeTimer
from app.prompts.query_understanding import query_understanding_prompt

logger = logging.getLogger(__name__)


async def query_understanding(state: FinAnalysisState) -> dict[str, Any]:
    """Parse user query to extract security ticker, name, industry, and intent.

    Uses LLM to interpret natural language query and produce structured JSON
    with security_ticker, security_name, industry, query_intent, etc.

    Args:
        state: Current graph state with raw user query.

    Returns:
        Dict with security_ticker, security_name, industry, query_intent,
        extra_context, and step log entry.
    """
    logger.info("[query_understanding] query=%s", state["query"])
    llm = get_llm()

    timer = NodeTimer()
    with timer:
        resp = await llm.ainvoke(
            query_understanding_prompt.invoke({"query": state["query"]})
        )

    content = resp.content.strip()
    # Strip markdown fences if model wraps in ```json ... ```
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("[query_understanding] Failed to parse JSON, using fallback")
        parsed = {
            "security_ticker": "",
            "security_name": state["query"],
            "industry": "",
            "query_intent": state["query"],
            "security_type": "EQUITY",
            "region": "United States",
            "exchange": None,
        }

    output = {
        "security_ticker": parsed.get("security_ticker", ""),
        "security_name": parsed.get("security_name", ""),
        "industry": parsed.get("industry", ""),
        "query_intent": parsed.get("query_intent", state["query"]),
        "extra_context": {
            "security_type": parsed.get("security_type", "EQUITY"),
            "region": parsed.get("region", ""),
            "exchange": parsed.get("exchange"),
        },
        "steps": [
            f"[query_understanding] ticker={parsed.get('security_ticker')} "
            f"industry={parsed.get('industry')}"
        ],
    }

    await log_node_execution(
        state["thread_id"],
        "query_understanding",
        {"query": state["query"]},
        output,
        timer.started_at,
        timer.elapsed_ms,
    )
    return output
