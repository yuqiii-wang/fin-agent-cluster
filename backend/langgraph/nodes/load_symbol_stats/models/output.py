"""Output models for load_symbol_stats node."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "BranchAttempt",
    "LoadSymbolStatsNodeOutput",
    "LoadSymbolStatsOutput",
]


class BranchAttempt(BaseModel):
    """Per-attempt audit record for the gacs branch."""

    branch: str = Field(description="Branch label (gacs).")
    attempt: int = Field(description="1-based attempt index for this branch.")
    ok: bool = Field(default=False, description="True when the attempt succeeded.")
    reason: str = Field(default="", description="Failure reason or brief summary.")
    orchestration_action: str | None = Field(
        default=None,
        description="llm_orchestration_on_failure action (retry_from_step / fail).",
    )
    orchestration_reasoning: str | None = Field(
        default=None,
        description="llm_orchestration_on_failure reasoning guidance.",
    )
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Any extra context captured for the attempt.",
    )

    model_config = {"extra": "allow"}


class LoadSymbolStatsNodeOutput(BaseModel):
    """Node-level output from the gacs branch.

    Attributes:
        symbol:   Queried ticker (for provenance).
        gacs:     Serialised ``GetAndCalculateStatsOutput`` (OHLCV pipeline).
        attempts: Per-branch attempt audit records from the outer retry loop.
    """

    symbol: str = Field(default="", description="Ticker that was processed.")
    gacs: dict[str, Any] | None = Field(
        default=None,
        description="gacs branch output (GetAndCalculateStatsOutput, serialised).",
    )
    attempts: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Per-branch attempt audit trail from the outer retry loop.",
    )

    model_config = {"extra": "allow"}


# Convenience alias -- ``LoadSymbolStatsOutput`` is the name used elsewhere
# when referencing node output, while ``LoadSymbolStatsNodeOutput`` is the
# fully-qualified / disambiguated form.
LoadSymbolStatsOutput = LoadSymbolStatsNodeOutput
