"""models — node-level I/O Pydantic models for news_node.

These models type the JSON payloads written to ``node_executions.input``
and ``node_executions.output`` via
:func:`~backend.sse_notifications.node_io.emit_node_input` /
:func:`~backend.sse_notifications.node_io.emit_node_output`.
"""

from __future__ import annotations

from pydantic import BaseModel


class NewsNodeInput(BaseModel):
    """Payload written to ``node_executions.input`` for the news node.

    Attributes:
        symbol:  Ticker symbol to fetch news for.
        limit:   Maximum number of articles to retrieve.
        node_id: Governance UUID for this node invocation.
        task_id: UUID of the fetch task created inside this node.
    """

    symbol: str
    limit: int
    node_id: str
    task_id: str


class NewsNodeOutput(BaseModel):
    """Payload written to ``node_executions.output`` for the news node.

    Attributes:
        symbol:        Ticker symbol.
        article_count: Number of articles fetched.
    """

    symbol: str
    article_count: int


__all__ = ["NewsNodeInput", "NewsNodeOutput"]
