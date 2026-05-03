"""mock_perf.nodes — individual LangGraph node functions for the mock_perf agent.

Sub-modules
-----------
perf_runner  — throughput / concurrency streaming performance-test node.
merge_node   — streaming fan-in merge (wraps Celery throughput task; mock_perf specific).

Shared nodes (from ``_shared.nodes``)
--------------------------------------
query_node  — query parser shared with mock_single.
news_node   — fetches mock news articles via NewsClient.
stats_node  — fetches mock market-stats records via StatsClient.
"""

from backend.graph.agents._shared.nodes.news_node import mock_news_node
from backend.graph.agents._shared.nodes.query_node import query_node
from backend.graph.agents._shared.nodes.stats_node import mock_stats_node
from backend.graph.agents.mock_perf.nodes.merge_node import merge_node
from backend.graph.agents.mock_perf.nodes.perf_runner import perf_runner

__all__ = [
    "perf_runner",
    "query_node",
    "mock_news_node",
    "mock_stats_node",
    "merge_node",
]
