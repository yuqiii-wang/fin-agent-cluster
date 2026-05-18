"""Tasks for analyze_stats_node."""

from backend.langgraph.nodes.mock_analyze_stats_node.tasks.analyze_stats import analyze_stats

HANDLERS: dict = {
    analyze_stats.name: analyze_stats.handler,
}

__all__ = ["analyze_stats", "HANDLERS"]
