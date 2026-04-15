"""app.graph — financial analysis LangGraph workflow package.

Sub-packages
------------
agents/   LangGraph node functions (one per node)
prompts/  LLM prompt templates (one module per node)
skills/   Domain-specific reusable capabilities (e.g. OHLCV processing)
tools/    Basic utility functions (ticker extraction, execution logging)

Public API
----------
``build_graph``        Constructs the uncompiled StateGraph.
``FinAnalysisState``   TypedDict that flows through every node.
"""

from backend.graph.builder import build_graph
from backend.graph.state import FinAnalysisState

__all__ = ["build_graph", "FinAnalysisState"]
