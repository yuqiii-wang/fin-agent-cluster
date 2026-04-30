"""fin_analyst — LangGraph agent package for financial analysis.

Exports the leaf-node function :func:`fin_analyst_runner` used by the
``fin_analyst_subgraph`` in the outer graph.
"""

from backend.graph.agents.fin_analyst.node import fin_analyst_runner

__all__ = ["fin_analyst_runner"]
