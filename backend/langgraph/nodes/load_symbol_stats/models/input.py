"""Input model for load_symbol_stats node."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["LoadSymbolStatsInput"]


class LoadSymbolStatsInput(BaseModel):
    """Typed input for ``load_symbol_stats``.

    Mirrors the configuration fields exposed on the node.

    Attributes:
        stock_symbol:            Queried ticker (from query_node output).
        period:                  Market-data period forwarded to ``get_stats``.
        pipeline:                Pipeline label forwarded to ``calculate_stats``.
        max_retries_per_branch:  Max retries (each retry consults the orchestrator).
        orchestration_enabled:   When True, failures invoke llm_orchestration_on_failure.
    """

    stock_symbol: str = Field(
        default="",
        description="Ticker of the stock under analysis; resolved from query_node output.",
    )
    period: str = Field(
        default="2y",
        description="Market-data period forwarded to get_stats.",
    )
    pipeline: str = Field(
        default="ohlcv",
        description="Pipeline label forwarded to calculate_stats (ohlcv / options / futures).",
    )
    max_retries_per_branch: int = Field(
        default=2,
        ge=0,
        le=10,
        description="Max retries (each retry consults the orchestrator).",
    )
    orchestration_enabled: bool = Field(
        default=True,
        description="When True, failures invoke llm_orchestration_on_failure.",
    )

    model_config = {"extra": "allow"}

    def __getitem__(self, key: str) -> Any:  # pragma: no cover - defensive
        return getattr(self, key)

    def __contains__(self, key: str) -> bool:  # pragma: no cover - defensive
        return hasattr(self, key)
