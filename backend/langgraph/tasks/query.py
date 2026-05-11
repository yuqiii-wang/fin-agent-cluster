"""Completion handlers for query_node tasks."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


async def handle_analyze_query(payload: dict[str, Any]) -> dict[str, Any]:
    """Parse the user query and extract intent + symbol list."""
    query: str = payload.get("query", "")
    logger.info("[analyze_query] query=%r", query)
    symbols = re.findall(r"\b[A-Z]{1,5}\b", query)
    return {
        "intent": "market_analysis",
        "symbols": symbols[:5] or ["AAPL"],
        "filters": {},
    }
