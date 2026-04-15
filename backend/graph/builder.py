"""Graph builder — assembles the 3-node financial analysis StateGraph.

Topology::

    START → query_optimizer → market_data_collector → decision_maker → END
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.graph.state import FinAnalysisState
from backend.graph.agents.query_optimizer import query_optimizer
from backend.graph.agents.market_data import market_data_collector
from backend.graph.agents.decision_maker import decision_maker


def build_graph() -> StateGraph:
    """Construct the 3-node financial analysis graph (uncompiled).

    Returns:
        A :class:`~langgraph.graph.StateGraph` ready to be compiled with a
        checkpointer and served via FastAPI.
    """
    builder = StateGraph(FinAnalysisState)

    builder.add_node("query_optimizer", query_optimizer)
    builder.add_node("market_data_collector", market_data_collector)
    builder.add_node("decision_maker", decision_maker)

    builder.add_edge(START, "query_optimizer")
    builder.add_edge("query_optimizer", "market_data_collector")
    builder.add_edge("market_data_collector", "decision_maker")
    builder.add_edge("decision_maker", END)

    return builder
