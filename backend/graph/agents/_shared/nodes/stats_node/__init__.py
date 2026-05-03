"""stats_node — mock market-stats fetching LangGraph node package.

Sub-modules
-----------
node   — :func:`mock_stats_node` thin LangGraph node function.
models — :class:`StatsNodeInput`, :class:`StatsNodeOutput` node-level I/O models.

Sub-packages
------------
tasks  — task functions for this node (stats fetch via StatsClient).
"""

from backend.graph.agents._shared.nodes.stats_node.node import mock_stats_node

__all__ = ["mock_stats_node"]
