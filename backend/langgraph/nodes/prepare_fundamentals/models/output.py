"""Output model for prepare_fundamentals node."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["PrepareFundamentalsOutput"]


class PrepareFundamentalsOutput(BaseModel):
    """Typed output for ``prepare_fundamentals``.

    Persisted to ``fin_agents.node_executions`` for downstream nodes.

    Attributes:
        stock_symbol: Equity ticker that fundamentals were searched for.
        method:       Which search_summary branch produced the answer
                      (``llm`` | ``ddgs`` | ``none``).
        answer:       Summarised textual answer from search_summary.
        sources:      List of source/citation dicts (title / url / snippet).
    """

    stock_symbol: str = Field(default="", description="Equity ticker that fundamentals were searched for.")
    method: str = Field(default="none", description="llm | ddgs | none")
    answer: str = Field(default="", description="Summarised textual answer from search_summary.")
    sources: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of source/citation dicts (title / url / snippet).",
    )
