"""Output model for conclusion_node.

Written to ``state["conclusion"]`` (the answer string) after the node
completes.  The full output is also persisted to ``fin_agents.nodes.output``.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

__all__ = ["ConclusionNodeOutput"]


class ConclusionNodeOutput(BaseModel):
    """Typed output for ``conclusion_node``.

    Attributes:
        answer: Full LLM-generated conclusion text (concatenated stream).
        thinking: Raw ``<think>…</think>`` content extracted from the stream,
            or ``None`` when the model did not emit a thinking block.
        total_tokens: Token count from the LLM response.
        latency_ms: End-to-end streaming latency in milliseconds.
    """

    answer: str = Field(default="", description="Full LLM-generated conclusion text.")
    thinking: Optional[str] = Field(default=None, description="Extracted <think> block content.")
    total_tokens: int = Field(default=0)
    latency_ms: int = Field(default=0)
