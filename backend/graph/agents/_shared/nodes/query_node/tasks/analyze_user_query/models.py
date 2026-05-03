"""query — Pydantic task-level I/O models for the query parsing task.

These models type the JSON stored in ``tasks.output`` (via
:func:`~backend.sse_notifications.complete_task`) and returned by
:func:`~backend.graph.agents._shared.nodes.query_node.tasks.analyze_user_query.workflow.run_analyze_user_query_task`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

class QueryTaskOutput(BaseModel):
    """Structured analysis request produced by the query task.

    Persisted to ``tasks.output`` and stored in graph state as
    ``query_response`` for downstream nodes to consume.

    Attributes:
        symbol:         Ticker symbol derived from the query.
        rationale:      Human-readable explanation of the parsed request.
    """

    symbol: str
    rationale: str
    industry: str = ""
    peers: list[str] = Field(default_factory=list)
    opposite_industry: str = ""
    opposite_industry_peers: list[str] = Field(default_factory=list)
    commodities: list[str] = Field(default_factory=list)
    cryptos: list[str] = Field(default_factory=list)

    def as_dict(self) -> dict:
        """Return a serialisable dict for node/task output storage."""
        return self.model_dump()


__all__ = ["QueryTaskOutput"]
