"""Input model for prepare_futures node."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["PrepareFuturesInput", "PrepareFuturesRequestItem", "PrepareFuturesRequestsInput"]


class PrepareFuturesInput(BaseModel):
    """Typed input for ``prepare_futures``.

    Attributes:
        stock_symbol:   Optional explicit symbol. When provided, the
                        node runs ``get_and_calculate_stats(futures)``
                        exactly *once* for that symbol and ignores the
                        macro_instruments catalogue.
        futures_period: Stats aggregation period passed to the plan
                        task (and thence to every ``get_and_calculate_stats``
                        fan-out item). Default ``"1y"``.
        maturity_horizon: Optional maturity horizon forwarded to the
                        indicator pipeline (interpreted the same way
                        as in :mod:`prepare_options`).
    """

    stock_symbol: str | None = Field(
        default=None,
        description=(
            "Optional explicit symbol. When provided, prepare_futures "
            "runs get_and_calculate_stats(futures) exactly once."
        ),
    )
    futures_period: str = Field(
        default="1y",
        description="Stats aggregation period (default '1y').",
    )
    maturity_horizon: Any = Field(
        default=None,
        description="Optional maturity horizon forwarded to the indicator pipeline.",
    )


from backend.langgraph.nodes.prepare_futures.tasks.prepare_futures_requests import (
    PrepareFuturesRequestItem,
    PrepareFuturesRequestsInput,
    PrepareFuturesRequestsOutput,
)

# Re-exported for discoverability.
__all__.extend(["PrepareFuturesRequestsOutput"])
