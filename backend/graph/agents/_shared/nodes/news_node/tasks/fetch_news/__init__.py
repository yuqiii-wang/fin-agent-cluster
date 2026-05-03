"""fetch_news — task sub-package for the news fetch stage."""

from backend.graph.agents._shared.nodes.news_node.tasks.fetch_news.workflow import run_fetch_news_task

__all__ = ["run_fetch_news_task"]
