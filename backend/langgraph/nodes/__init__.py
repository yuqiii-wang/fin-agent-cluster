"""Nodes package for the fin-analysis LangGraph.

Exports
-------
Node callables (registered with LangGraph StateGraph):
    query_node, research_subgraph, analyze_stats_node, analyze_news_node,
    conclusion_node, apac_analyze_node, emea_analyze_node, amer_analyze_node

HANDLERS registry (consumed by the Celery completion worker):
    Flat dict mapping task_name → async handler assembled from each node's
    tasks sub-package.  Streaming tasks (stream_llm) are excluded
    because they run via a separate Celery stream worker.
"""

from backend.langgraph.nodes.query_node import query_node
from backend.langgraph.nodes.query_node import HANDLERS as _QH
from backend.langgraph.nodes.mock_query_node import HANDLERS as _MOCK_QH
from backend.langgraph.nodes.mock_research_subgraph import research_subgraph
from backend.langgraph.nodes.mock_research_subgraph import HANDLERS as _RH
from backend.langgraph.nodes.mock_analyze_stats_node import analyze_stats_node
from backend.langgraph.nodes.mock_analyze_stats_node import HANDLERS as _ASH
from backend.langgraph.nodes.mock_analyze_news_node import analyze_news_node
from backend.langgraph.nodes.mock_analyze_news_node import HANDLERS as _ANH
from backend.langgraph.nodes.mock_conclusion_node import conclusion_node
from backend.langgraph.nodes.mock_conclusion_node import HANDLERS as _CH
from backend.langgraph.nodes.mock_regional_analyze_nodes import (
    apac_analyze_node,
    emea_analyze_node,
    amer_analyze_node,
)
from backend.langgraph.nodes.mock_regional_analyze_nodes import HANDLERS as _RAH

# Global HANDLERS registry consumed by completion_task.run_completion.
# Mock handlers use distinct names (e.g. "mock_analyze_query") to avoid
# colliding with real task handlers registered under the same logical name.
HANDLERS: dict = {**_QH, **_RH, **_ASH, **_ANH, **_CH, **_RAH, **_MOCK_QH}

__all__ = [
    "query_node",
    "research_subgraph",
    "conclusion_node",
    "apac_analyze_node",
    "emea_analyze_node",
    "amer_analyze_node",
    "HANDLERS",
]
