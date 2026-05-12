"""Input model for query_node.

Reads ``state["query"]`` and carries it as a typed field so downstream
task code never needs to reach into the raw state dict.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["QueryNodeInput"]


class QueryNodeInput(BaseModel):
    """Typed input for ``query_node`` and its ``analyze_query`` task.

    Attributes:
        query: Raw user query string from the thread initiator.
    """

    query: str = Field(description="Raw user query string.")
