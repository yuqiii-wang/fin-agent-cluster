"""app.graph — streaming LangGraph workflow package.

Sub-packages
------------
agents/   LangGraph node functions (mock leaf node)

Public API
----------
``build_graph``     Constructs the two-level streaming graph.
``StreamRunState``  TypedDict that flows through the graph.
"""

from backend.graph.builder import build_graph
from backend.graph.state import StreamRunState

__all__ = [
    "build_graph",
    "StreamRunState",
]
