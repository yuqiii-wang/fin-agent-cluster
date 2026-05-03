"""mock_single.nodes — LangGraph node functions for the mock single-request agent.

Sub-packages
------------
analysis_node — LLM ingest/digest of merged_analysis via Celery throughput stream.

Sub-modules
-----------
news_node  — fetches mock news articles via NewsClient.
stats_node — fetches mock market-stats records via StatsClient.

Shared nodes (from ``_shared.nodes``)
--------------------------------------
query_node — query parser (shared with mock_perf).
merge_node — pure JSON aggregator fan-in (shared with mock_perf).
"""

from backend.graph.agents._shared.nodes.merge_node import merge_node
from backend.graph.agents._shared.nodes.news_node import mock_news_node
from backend.graph.agents._shared.nodes.query_node import query_node
from backend.graph.agents._shared.nodes.stats_node import mock_stats_node
from backend.graph.agents.mock_single.nodes.analysis_node import mock_analysis_node

__all__ = [
    "query_node",
    "mock_news_node",
    "mock_stats_node",
    "merge_node",
    "mock_analysis_node",
]
