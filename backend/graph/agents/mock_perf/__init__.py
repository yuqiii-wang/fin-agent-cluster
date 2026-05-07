"""mock_perf — LangGraph agent package for the mock streaming and analysis workflows.

Exports :func:`build_mock_perf_subgraph` used by the outer graph builder, along
with the trigger phrase constants so the outer router can recognise them.
"""

from backend.graph.agents.mock_perf.graph import (
    PERF_TEST_TRIGGER,
    build_mock_perf_subgraph,
)

__all__ = ["build_mock_perf_subgraph", "PERF_TEST_TRIGGER"]
