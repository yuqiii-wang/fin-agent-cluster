"""Tasks for query_node."""

from backend.langgraph.nodes.query_node.tasks.analyze_query import analyze_query
from backend.langgraph.nodes.query_node.tasks.capture_time import capture_time

HANDLERS: dict = {
    analyze_query.name: analyze_query.handler,
    capture_time.name: capture_time.handler,
}

__all__ = ["analyze_query", "capture_time", "HANDLERS"]
