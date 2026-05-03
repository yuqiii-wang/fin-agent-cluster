"""models — node-level I/O Pydantic models for stats_node.

These models type the JSON payloads written to ``node_executions.input``
and ``node_executions.output`` via
:func:`~backend.sse_notifications.node_io.emit_node_input` /
:func:`~backend.sse_notifications.node_io.emit_node_output`.
"""

from __future__ import annotations

from pydantic import BaseModel


class StatsNodeInput(BaseModel):
    """Payload written to ``node_executions.input`` for the stats node.

    Attributes:
        symbol:  Ticker symbol to fetch stats for.
        period:  Time period for the stats query (e.g. ``"1d"``).
        node_id: Governance UUID for this node invocation.
        task_id: UUID of the fetch task created inside this node.
    """

    symbol: str
    period: str
    node_id: str
    task_id: str


class StatsNodeOutput(BaseModel):
    """Payload written to ``node_executions.output`` for the stats node.

    Attributes:
        symbol:       Ticker symbol.
        period:       Time period queried.
        record_count: Number of stats records fetched.
    """

    symbol: str
    period: str
    record_count: int


__all__ = ["StatsNodeInput", "StatsNodeOutput"]
