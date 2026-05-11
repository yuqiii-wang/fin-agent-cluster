"""Completion handlers for query_node tasks."""

from __future__ import annotations

import logging
import re

from backend.langgraph.models import AnalyzeQueryInput, AnalyzeQueryOutput

logger = logging.getLogger(__name__)


async def handle_analyze_query(payload: dict) -> dict:
    """Parse the user query and extract intent + symbol list."""
    inp = AnalyzeQueryInput.model_validate(payload)
    symbols = re.findall(r"\b[A-Z]{1,5}\b", inp.query)
    output = AnalyzeQueryOutput(
        intent="market_analysis",
        symbols=symbols[:5] or ["AAPL"],
        filters={},
    )
    return output.model_dump()

