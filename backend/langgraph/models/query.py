"""Content models for the query_node / analyze_query task.

These represent the ``input`` and ``output`` JSONB columns stored in
``fin_agents.tasks`` and ``fin_agents.nodes`` for the query processing step.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "AnalyzeQueryInput",
    "AnalyzeQueryOutput",
]


class AnalyzeQueryInput(BaseModel):
    """Input payload for the ``analyze_query`` task and ``query_node``.

    Stored as ``input`` JSONB in ``fin_agents.tasks`` and ``fin_agents.nodes``.
    """

    query: str = Field(description="Raw user query string.")


class AnalyzeQueryOutput(BaseModel):
    """Output payload for the ``analyze_query`` task and ``query_node``.

    Stored as ``output`` JSONB in ``fin_agents.tasks`` and ``fin_agents.nodes``.
    Also stored as the ``query_analysis`` slice of :class:`~backend.langgraph.state.GraphState`.
    """

    intent: str = Field(description="Classified query intent (e.g. 'market_analysis').")
    symbols: list[str] = Field(default_factory=list, description="Equity ticker symbols extracted from the query.")
    filters: dict[str, Any] = Field(default_factory=dict, description="Optional filter key/values (e.g. date range, interval).")
