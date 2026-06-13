"""AAPL-themed word pools and token sequence builder for semantic mock mode."""

from __future__ import annotations

import itertools

_AAPL_NOUNS: tuple[str, ...] = (
    "AAPL", "stock", "share", "price", "market",
    "rally", "earnings", "revenue", "dividend", "momentum",
    "bull", "bear", "trend", "support", "resistance",
)

_AAPL_VERBS: tuple[str, ...] = (
    "surges", "rallies", "climbs", "drops", "consolidates",
    "rebounds", "targets", "beats", "misses", "breaks",
)

_AAPL_ADJS: tuple[str, ...] = (
    "bullish", "bearish", "volatile", "strong", "weak",
    "oversold", "overbought", "positive", "negative", "technical",
)

SEMANTIC_TOKENS_PER_SEC: float = 30.0
SEMANTIC_DURATION_SECS: int = 10


def build_semantic_token_pool() -> list[str]:
    """Return an ordered pool of AAPL phrases from word combinations."""
    return (
        [f"{a} {n}" for a, n in itertools.product(_AAPL_ADJS, _AAPL_NOUNS)]
        + [f"{n} {v}" for n, v in itertools.product(_AAPL_NOUNS, _AAPL_VERBS)]
        + [f"{a} {v}" for a, v in itertools.product(_AAPL_ADJS, _AAPL_VERBS)]
    )


__all__ = [
    "SEMANTIC_TOKENS_PER_SEC",
    "SEMANTIC_DURATION_SECS",
    "build_semantic_token_pool",
]
