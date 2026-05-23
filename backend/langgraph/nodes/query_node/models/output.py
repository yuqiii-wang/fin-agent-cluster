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
    """

    stock_name: str = Field(description="Company name or stock ticker extracted from the query.")
