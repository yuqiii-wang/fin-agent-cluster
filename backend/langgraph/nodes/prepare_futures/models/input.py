"""Input model for prepare_futures node."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["PrepareFuturesInput"]


class PrepareFuturesInput(BaseModel):
    """Typed input for ``prepare_futures``.

    Attributes:
        period: Stats aggregation period passed to ``get_and_calculate_stats``
                for every futures instrument.
    """

    period: str = Field(
        default="1y",
        description="Stats aggregation period passed to get_and_calculate_stats.",
    )
