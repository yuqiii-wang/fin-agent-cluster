"""Tasks for research_subgraph."""

from backend.langgraph.nodes.mock_research_subgraph.tasks.read_stats import read_stats
from backend.langgraph.nodes.mock_research_subgraph.tasks.read_news import read_news
from backend.langgraph.nodes.mock_research_subgraph.tasks.merge_results import merge_results

HANDLERS: dict = {
    read_stats.name: read_stats.handler,
    read_news.name: read_news.handler,
    merge_results.name: merge_results.handler,
}

__all__ = ["read_stats", "read_news", "merge_results", "HANDLERS"]
