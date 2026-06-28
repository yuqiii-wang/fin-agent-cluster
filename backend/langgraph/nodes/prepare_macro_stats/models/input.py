"""Input model for prepare_macro_stats node."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["AnalyzeEconomicsInput"]


class AnalyzeEconomicsInput(BaseModel):
    """Typed input for ``prepare_macro_stats``.

    Attributes:
        period: Stats aggregation period passed to ``get_and_calculate_stats``
                for all economics instruments.
    """

    period: str = Field(default="1y", description="Stats aggregation period, e.g. '1y'.")
