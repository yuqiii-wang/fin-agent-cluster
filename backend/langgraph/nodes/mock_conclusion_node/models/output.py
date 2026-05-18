"""Output model for conclusion_node.

The node uses view_type="Hybrid" with view_schema:
    streaming → "Mirror"  (references stream_conclusion task; shows thinking)
    answer    → "Json"    (structured LLM conclusion written to node output)

Written to ``state["conclusion"]`` (JSON-serialised answer dict) after the
node completes so executor.py can pass it to ``complete_thread``.
The full output including the streaming Mirror ref is also persisted to
``fin_agents.node_executions.output``.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

__all__ = ["ConclusionNodeOutput"]


class ConclusionNodeOutput(BaseModel):
    """Typed output for ``conclusion_node``.

    Attributes:
        streaming: Mirror reference ``{"task_id": "<stream_conclusion task id>"}``
            resolved by the frontend to show the streaming thinking view.
        answer: Structured LLM-generated conclusion as a JSON dict.
            Expected keys: summary, recommendation, confidence, key_points,
            risk_factors.
        thinking: Raw ``<think>…</think>`` content extracted from the stream,
            or ``None`` when the model did not emit a thinking block.
        total_tokens: Token count from the LLM response.
        latency_ms: End-to-end streaming latency in milliseconds.
    """

    streaming: dict[str, Any] = Field(
        default_factory=dict,
        description='Mirror ref: {"task_id": "<stream_conclusion task id>"}.',
    )
    answer: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured LLM conclusion (summary, recommendation, confidence, key_points, risk_factors).",
    )
    thinking: Optional[str] = Field(default=None, description="Extracted <think> block content.")
    total_tokens: int = Field(default=0)
    latency_ms: int = Field(default=0)
