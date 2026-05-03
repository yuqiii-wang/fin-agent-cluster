"""_shared.nodes — re-usable LangGraph node functions shared across agents.

Nodes
-----
query_node  — query-parser node (used by mock_perf and mock_single).
merge_node  — pure JSON aggregator fan-in node (used by mock_single; mock_perf
              has its own streaming merge variant).

Each node is a package containing:
  node.py    — thin LangGraph node function
  models.py  — node-level I/O Pydantic models
  tasks/     — task sub-packages (workflow.py + models.py per task)
"""

from backend.graph.agents._shared.nodes.merge_node import merge_node
from backend.graph.agents._shared.nodes.news_node import mock_news_node
from backend.graph.agents._shared.nodes.query_node import query_node
from backend.graph.agents._shared.nodes.stats_node import mock_stats_node

__all__ = ["query_node", "merge_node", "mock_news_node", "mock_stats_node"]
