"""Static task name registry for the streaming workflow.

Task names identify specific task types for frontend handling.

``STREAM_KEYS`` enumerates every name whose task writes ``token_batch`` events to
``fin:llm:tokens`` — used by the Tasks API to classify streaming tasks.

``STATIC_KEYS`` enumerates every static task name.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# stream_runner names
# ---------------------------------------------------------------------------

STREAM_RUNNER_THROUGHPUT: str = "stream_runner_throughput"
STREAM_RUNNER_CONCURRENCY: str = "stream_runner_concurrency"

# ---------------------------------------------------------------------------
# mock_perf / mock_single names
# ---------------------------------------------------------------------------

MOCK_RUNNER_CONCURRENCY: str = "MOCK_RUNNER_CONCURRENCY"
"""
Task name used by both mock_perf (concurrency mode) and mock_single
(analysis_node) — emits ``token_batch`` events at a fixed TPS rate.
"""

# ---------------------------------------------------------------------------
# fin_analyst names
# ---------------------------------------------------------------------------

FIN_ANALYST_ANALYSIS: str = "fin_analyst_analysis"

# ---------------------------------------------------------------------------
# query_node names
# ---------------------------------------------------------------------------

ANALYZE_USER_QUERY: str = "analyze_user_query"
ADD_STATIC_QUERY_METRICS: str = "add_static_query_metrics"

# ---------------------------------------------------------------------------
# Key sets
# ---------------------------------------------------------------------------

STREAM_KEYS: frozenset[str] = frozenset({STREAM_RUNNER_THROUGHPUT, STREAM_RUNNER_CONCURRENCY, MOCK_RUNNER_CONCURRENCY})
"""Task names that write ``token_batch`` events to ``fin:llm:tokens``."""

STATIC_KEYS: frozenset[str] = frozenset({
    STREAM_RUNNER_THROUGHPUT,
    STREAM_RUNNER_CONCURRENCY,
    MOCK_RUNNER_CONCURRENCY,
    FIN_ANALYST_ANALYSIS,
    ANALYZE_USER_QUERY,
    ADD_STATIC_QUERY_METRICS,
})
"""All static literal task names."""

LLM_STREAM_KEYS: frozenset[str] = frozenset()
"""No traditional LLM stream names — streaming uses the Celery path."""

PERF_TOKEN_KEYS: frozenset[str] = STREAM_KEYS
"""Names that emit token_batch events."""
