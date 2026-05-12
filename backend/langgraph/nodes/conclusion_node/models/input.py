"""Input model for conclusion_node.

Reads two state slices:
  - state["merged_research"]  — MergeOutput serialised from research_subgraph
  - state["query"]            — original user query for LLM context
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["ConclusionNodeInput"]


class ConclusionNodeInput(BaseModel):
    """Typed input for ``conclusion_node`` and its ``stream_conclusion`` task.

    Attributes:
        merged_research: Serialised ``MergeOutput`` dict from research_subgraph.
        query: Original user query string for LLM prompt context.
    """

    merged_research: dict[str, Any] = Field(default_factory=dict)
    query: str = Field(default="", description="Original user query for LLM context.")
