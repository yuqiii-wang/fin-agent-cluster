"""Tasks for analyze_news_node."""

from backend.langgraph.nodes.mock_analyze_news_node.tasks.analyze_news import analyze_news

HANDLERS: dict = {
    analyze_news.name: analyze_news.handler,
}

__all__ = ["analyze_news", "HANDLERS"]
