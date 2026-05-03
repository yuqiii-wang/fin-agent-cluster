"""models — node-level I/O Pydantic models for merge_node.

These models type the JSON payloads written to ``node_executions.input``
and ``node_executions.output`` via
:func:`~backend.sse_notifications.node_io.emit_node_input` /
:func:`~backend.sse_notifications.node_io.emit_node_output`.

Task-level models (the merged analysis output shape) live in
:mod:`backend.graph.agents._shared.nodes.merge_node.tasks.merge.models`.
"""

from __future__ import annotations

from pydantic import BaseModel


class MergeNodeInput(BaseModel):
    """Payload written to ``node_executions.input`` for the merge node.

    Attributes:
        article_count:     Number of news articles received from upstream.
        stat_record_count: Number of market-stats records received.
        node_id:           Governance UUID for this node invocation.
        task_id:           UUID of the merge task created inside this node.
    """

    article_count: int
    stat_record_count: int
    node_id: str
    task_id: str


class MergeNodeOutput(BaseModel):
    """Payload written to ``node_executions.output`` for the merge node.

    Attributes:
        symbol:       Ticker symbol.
        news_count:   Number of aggregated news articles.
        stats_count:  Number of aggregated stats records.
        merged_keys:  Top-level keys present in the ``merged_analysis`` dict.
    """

    symbol: str
    news_count: int
    stats_count: int
    merged_keys: list[str]


__all__ = ["MergeNodeInput", "MergeNodeOutput"]
