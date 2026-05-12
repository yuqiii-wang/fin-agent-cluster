"""Tasks for query_node."""

from backend.langgraph.nodes.query_node.tasks.analyze_query import analyze_query

HANDLERS: dict = {
    analyze_query.name: analyze_query.handler,
}

__all__ = ["analyze_query", "HANDLERS"]
