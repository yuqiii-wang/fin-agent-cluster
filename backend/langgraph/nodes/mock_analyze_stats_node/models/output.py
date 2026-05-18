"""Output model for analyze_stats_node."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["AnalyzeStatsOutput"]


class AnalyzeStatsOutput(BaseModel):
    """Typed output for ``analyze_stats_node``.

    Attributes:
        symbol: The primary ticker that was analysed.
        stats_analysis: Human-readable narrative of the statistical findings.
        key_metrics: Dict of computed metrics (return_pct, volatility, trend, etc.).
    """

    symbol: str = Field(default="")
    stats_analysis: str = Field(default="", description="Narrative statistical analysis.")
    key_metrics: dict[str, Any] = Field(default_factory=dict)
