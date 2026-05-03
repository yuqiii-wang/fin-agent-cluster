"""news_node.tasks — task functions for the news fetch node."""

from backend.graph.agents._shared.nodes.news_node.tasks.fetch_news import run_fetch_news_task

__all__ = ["run_fetch_news_task"]
