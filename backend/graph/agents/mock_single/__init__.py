"""mock_single — LangGraph agent package for the mock single-request analysis workflow.

Exports :func:`build_mock_single_subgraph` used by the outer graph builder and
:data:`MOCK_SINGLE_TRIGGER` so the outer router can recognise the trigger phrase.
"""

from backend.graph.agents.mock_single.graph import (
    MOCK_SINGLE_TRIGGER,
    build_mock_single_subgraph,
)

__all__ = ["build_mock_single_subgraph", "MOCK_SINGLE_TRIGGER"]
