"""Nodes package for the fin-analysis LangGraph.

Exports
-------
Node callables (registered with LangGraph StateGraph):
    query_node, research_subgraph, conclusion_node

HANDLERS registry (consumed by the Celery completion worker):
    Flat dict mapping task_name → async handler assembled from each node's
    tasks sub-package.  Streaming tasks (stream_conclusion) are excluded
    because they run via a separate Celery stream worker.
"""

from backend.langgraph.nodes.query_node import query_node
from backend.langgraph.nodes.query_node import HANDLERS as _QH
from backend.langgraph.nodes.research_subgraph import research_subgraph
from backend.langgraph.nodes.research_subgraph import HANDLERS as _RH
from backend.langgraph.nodes.conclusion_node import conclusion_node
from backend.langgraph.nodes.conclusion_node import HANDLERS as _CH

# Global HANDLERS registry consumed by completion_task.run_completion.
HANDLERS: dict = {**_QH, **_RH, **_CH}

__all__ = ["query_node", "research_subgraph", "conclusion_node", "HANDLERS"]
