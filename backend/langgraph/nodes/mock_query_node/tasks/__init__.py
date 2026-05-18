"""Tasks for mock_query_node."""

from backend.langgraph.nodes.mock_query_node.tasks.analyze_query import analyze_query

HANDLERS: dict = {
    analyze_query.name: analyze_query.handler,  # "mock_analyze_query"
}

__all__ = ["analyze_query", "HANDLERS"]
