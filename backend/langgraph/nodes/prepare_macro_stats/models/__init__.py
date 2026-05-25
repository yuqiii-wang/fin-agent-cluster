"""Models package for analyze_economics node."""

from backend.langgraph.nodes.prepare_macro_stats.models.input import AnalyzeEconomicsInput
from backend.langgraph.nodes.prepare_macro_stats.models.output import (
    AnalyzeEconomicsOutput,
    EconomicsInstrumentResult,
)

__all__ = ["AnalyzeEconomicsInput", "AnalyzeEconomicsOutput", "EconomicsInstrumentResult"]
