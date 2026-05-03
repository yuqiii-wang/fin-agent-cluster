"""models — node-level I/O Pydantic models for query_node.

These models type the JSON payloads written to ``node_executions.input``
and ``node_executions.output`` via
:func:`~backend.sse_notifications.node_io.emit_node_input` /
:func:`~backend.sse_notifications.node_io.emit_node_output`.

Task-level models (the structured analysis request produced by the query
task itself) live in
:mod:`backend.graph.agents._shared.nodes.query_node.tasks.analyze_user_query.models`.
"""

from __future__ import annotations

from pydantic import BaseModel

from backend.graph.agents._shared.nodes.query_node.tasks.analyze_user_query.models import QueryTaskOutput


class QueryNodeInput(BaseModel):
    """Payload written to ``node_executions.input`` for the query node.

    Attributes:
        query:    Raw user query string from graph state.
        node_id:  Governance UUID for this node invocation.
        task_id:  UUID of the task created inside this node.
    """

    query: str
    node_id: str
    task_id: str


class QueryNodeOutput(BaseModel):
    """Payload written to ``node_executions.output`` for the query node.

    Attributes:
        query_response: Full structured analysis request produced by the task.
    """

    query_response: QueryTaskOutput


__all__ = ["QueryNodeInput", "QueryNodeOutput"]
