"""Content models for the conclusion_node / stream_conclusion task.

These represent the ``input`` and ``output`` JSONB columns stored in
``fin_agents.tasks`` and ``fin_agents.nodes`` for the conclusion streaming step.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "StreamConclusionInput",
    "StreamConclusionOutput",
]


class StreamConclusionInput(BaseModel):
    """Input payload for the ``stream_conclusion`` task and ``conclusion_node``."""

    merged_research: dict[str, Any] = Field(default_factory=dict)
    query: str = Field(default="", description="Original user query for context.")


class StreamConclusionOutput(BaseModel):
    """Output payload for the ``stream_conclusion`` task and ``conclusion_node``."""

    answer: str = Field(default="", description="Full LLM-generated conclusion text.")
    total_tokens: int = Field(default=0)
    latency_ms: int = Field(default=0)
