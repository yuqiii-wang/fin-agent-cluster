"""Output model for query_node.

Persisted to ``fin_agents.node_executions`` for the ``query_node`` row.
Downstream nodes read this via ``read_node_output(node_id)``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["QueryNodeOutput"]


class QueryNodeOutput(BaseModel):
    """Typed output for ``query_node``.

    Attributes:
        stock_name: Company or stock ticker extracted from the user query.
        region: Primary exchange region of the stock (APAC, EMEA, or AMER).
        industry: Primary industry sector the company operates in.
        peers: List of peer companies operating in a similar business and region.
    """

    stock_name: str = Field(description="Company name or stock ticker extracted from the query.")
    region: str = Field(description="Primary exchange region: APAC, EMEA, or AMER.")
    industry: str = Field(description="Primary industry sector of the company.")
    peers: list[str] = Field(default_factory=list, description="Peer companies in similar business and region.")
