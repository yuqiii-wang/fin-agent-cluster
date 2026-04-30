"""Pydantic models for the fin_analyst agent input/output."""

from __future__ import annotations

from pydantic import BaseModel


class FinAnalystInput(BaseModel):
    """Input to the fin_analyst node."""

    thread_id: str
    query: str


class FinAnalystOutput(BaseModel):
    """Output produced by the fin_analyst node."""

    summary: str
    confidence: float

    def as_dict(self) -> dict:
        """Return a plain dict for node execution log storage."""
        return {"summary": self.summary, "confidence": self.confidence}


__all__ = ["FinAnalystInput", "FinAnalystOutput"]
