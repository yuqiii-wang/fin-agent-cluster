"""Ticker symbol extraction utility."""

from __future__ import annotations

import re
from typing import Optional

_SKIP_WORDS: frozenset[str] = frozenset({
    "I", "A", "AN", "THE", "BUY", "SELL", "FOR", "OR", "AND", "IS", "IN",
    "ON", "AT", "TO", "DO", "IF", "BE", "US", "WAS", "ARE", "MY", "ME",
    "WE", "IT", "AS", "BY",
})


def extract_ticker(query: str) -> Optional[str]:
    """Heuristically extract a ticker symbol from a natural-language query.

    Looks for standalone uppercase words of 1–5 characters, ignoring common
    English stop-words that would otherwise match.

    Args:
        query: Raw user query string.

    Returns:
        The first plausible ticker found, or ``None``.
    """
    for match in re.findall(r'\b[A-Z]{1,5}\b', query):
        if match not in _SKIP_WORDS:
            return match
    return None
