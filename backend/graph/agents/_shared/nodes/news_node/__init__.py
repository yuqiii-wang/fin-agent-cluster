"""news_node — mock news-fetching LangGraph node package.

Sub-modules
-----------
node   — :func:`mock_news_node` thin LangGraph node function.
models — :class:`NewsNodeInput`, :class:`NewsNodeOutput` node-level I/O models.

Sub-packages
------------
tasks  — task functions for this node (news fetch via NewsClient).
"""

from backend.graph.agents._shared.nodes.news_node.node import mock_news_node

__all__ = ["mock_news_node"]
