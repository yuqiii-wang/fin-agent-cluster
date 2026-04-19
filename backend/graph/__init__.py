"""app.graph — financial analysis LangGraph workflow package.

Sub-packages
------------
agents/   LangGraph node functions (one per node)
prompts/  LLM prompt templates (one module per node)
skills/   Domain-specific reusable capabilities (e.g. OHLCV processing)
tools/    Basic utility functions (ticker extraction, execution logging)

Public API
----------
``build_unified_graph``         Constructs the unified parent graph (routes fin-analysis OR perf-test).
``PERF_TEST_TRIGGER``           Trigger query string for the perf-test branch.
``UnifiedGraphState``           TypedDict that flows through the unified graph.
``build_graph``                 Constructs the fin-analysis-only graph (legacy; kept for tests).
``FinAnalysisState``            TypedDict for the fin-analysis pipeline.
``PerfTestState``               TypedDict for the perf-test node.
"""

from backend.graph.builder import (
    PERF_TEST_TRIGGER,
    build_graph,
    build_streaming_perf_test_graph,
    build_unified_graph,
)
from backend.graph.state import FinAnalysisState, PerfTestState, UnifiedGraphState

__all__ = [
    "PERF_TEST_TRIGGER",
    "build_graph",
    "build_streaming_perf_test_graph",
    "build_unified_graph",
    "FinAnalysisState",
    "PerfTestState",
    "UnifiedGraphState",
]
