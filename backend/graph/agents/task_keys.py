"""Static task key registry for the streaming workflow.

Task keys follow the dot-separated pattern ``<node>.<method>``.

``STREAM_KEYS`` enumerates every key whose task writes ``token_batch`` events to
``fin:llm:tokens`` — used by the Tasks API to classify streaming tasks.

``STATIC_KEYS`` enumerates every static task key.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# stream_runner keys
# ---------------------------------------------------------------------------

STREAM_RUNNER_THROUGHPUT: str = "stream_runner.throughput"
"""Throughput-mode streaming task — bulk-writes ``token_batch`` events via Celery."""

STREAM_RUNNER_CONCURRENCY: str = "stream_runner.concurrency"
"""Concurrency-mode streaming task — rate-limited ``token_batch`` events via Celery."""

# ---------------------------------------------------------------------------
# fin_analyst keys
# ---------------------------------------------------------------------------

FIN_ANALYST_ANALYSIS: str = "fin_analyst.analysis"
"""Dummy financial analysis task — emits lifecycle events only (no token stream)."""

# ---------------------------------------------------------------------------
# Key sets
# ---------------------------------------------------------------------------

STREAM_KEYS: frozenset[str] = frozenset({STREAM_RUNNER_THROUGHPUT, STREAM_RUNNER_CONCURRENCY})
"""Task keys that write ``token_batch`` events to ``fin:llm:tokens``."""

STATIC_KEYS: frozenset[str] = frozenset({
    STREAM_RUNNER_THROUGHPUT,
    STREAM_RUNNER_CONCURRENCY,
    FIN_ANALYST_ANALYSIS,
})
"""All static literal task keys."""

LLM_STREAM_KEYS: frozenset[str] = frozenset()
"""No traditional LLM stream keys — streaming uses the Celery path."""

PERF_TOKEN_KEYS: frozenset[str] = STREAM_KEYS
"""Keys that emit token_batch events."""

