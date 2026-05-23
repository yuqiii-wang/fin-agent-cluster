"""Fin-analysis LangGraph package.

Public API
----------
:func:`run_analysis`      — run the full graph for one user query.
:data:`fin_analysis_graph` — pre-compiled graph (no checkpointer).

Hierarchy: Thread → Node → Task
  - Thread  = one ``run_analysis`` invocation (one ``thread_id``)
  - Node    = one LangGraph node function (query_node, research_subgraph,
              stats_node, news_node, merge_node, conclusion_node)
  - Task    = one ``@task``-decorated unit inside a node, delegated to
              a Celery worker; results gathered back in the LangGraph thread.

Imports from this package are deferred to avoid loading the full node and
Celery task chain at startup before connection pools are open.
"""

from __future__ import annotations


def __getattr__(name: str):  # noqa: N807
    if name in ("fin_analysis_graph", "run_analysis"):
        from backend.langgraph.graphs.fin_trading_graph import run_analysis
        from backend.langgraph.graphs.fin_trading_graph import fin_trading_graph as fin_analysis_graph
        return locals()[name]
    if name == "GraphState":
        from backend.langgraph.state import GraphState
        return GraphState
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["fin_analysis_graph", "run_analysis", "GraphState"]

