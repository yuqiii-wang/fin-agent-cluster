"""Models package for analyze_economics node."""

from backend.langgraph.nodes.prepare_macro.models.input import AnalyzeEconomicsInput
from backend.langgraph.nodes.prepare_macro.models.output import (
    AnalyzeEconomicsOutput,
    EconomicsInstrumentResult,
)

__all__ = ["AnalyzeEconomicsInput", "AnalyzeEconomicsOutput", "EconomicsInstrumentResult"]
