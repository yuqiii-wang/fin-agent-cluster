"""Nodes package for the fin-trading LangGraph.

Exports
-------
Node callables (registered with LangGraph StateGraph):
    query_node, prepare_peers_node, prepare_macro_stats_node, prepare_index_node,
    prepare_derivatives_node

HANDLERS registry (consumed by the Celery completion worker):
    Flat dict mapping task_name → async handler assembled from each node's
    tasks sub-package.  Streaming tasks (stream_llm) are excluded
    because they run via a separate Celery stream worker.

NODE_REGISTRY:
    Flat dict mapping node_name (str) → BaseNode instance.  Used by the
    agent capabilities API to look up NodeTask descriptions and input
    schemas without hitting the DB.
"""

from backend.langgraph.nodes.query_node import query_node
from backend.langgraph.nodes.query_node import HANDLERS as _QH
from backend.langgraph.nodes.prepare_peers import prepare_peers_node
from backend.langgraph.nodes.prepare_macro_stats import prepare_macro_stats_node
from backend.langgraph.nodes.prepare_index import prepare_index_node
from backend.langgraph.nodes.prepare_news import prepare_news_node
from backend.langgraph.nodes.prepare_industry_news import prepare_industry_news_node
from backend.langgraph.nodes.prepare_macro_news import prepare_macro_news_node
from backend.langgraph.nodes.prepare_derivatives import prepare_derivatives_node
from backend.langgraph.models.common_tasks import HANDLERS as _CTH

# Global HANDLERS registry consumed by completion_task.run_completion.
HANDLERS: dict = {**_QH, **_CTH}

# Registry mapping node_name → node instance.
NODE_REGISTRY: dict = {
    node.node_name: node
    for node in [
        query_node,
        prepare_peers_node,
        prepare_macro_stats_node,
        prepare_index_node,
        prepare_news_node,
        prepare_industry_news_node,
        prepare_macro_news_node,
        prepare_derivatives_node,
    ]
}

__all__ = [
    "query_node",
    "prepare_peers_node",
    "prepare_macro_stats_node",
    "prepare_index_node",
    "prepare_news_node",
    "prepare_industry_news_node",
    "prepare_macro_news_node",
    "prepare_derivatives_node",
    "HANDLERS",
    "NODE_REGISTRY",
]
