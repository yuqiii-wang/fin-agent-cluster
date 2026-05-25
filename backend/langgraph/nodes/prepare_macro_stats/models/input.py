"""Input model for analyze_economics node."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["AnalyzeEconomicsInput"]


class AnalyzeEconomicsInput(BaseModel):
    """Typed input for ``analyze_economics``.

    Attributes:
        period: Stats aggregation period passed to ``get_and_calculate_stats``
                for all economics instruments.
    """

    period: str = Field(default="2y", description="Stats aggregation period, e.g. '2y'.")
