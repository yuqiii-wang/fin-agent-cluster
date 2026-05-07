"""report_node — trading signal report node package for the mock single-request pipeline.

Sub-modules
-----------
node    — :func:`mock_report_node` thin LangGraph node function.

Sub-packages
------------
tasks   — task functions for this node (opt-in streaming report generation).
"""

from backend.graph.agents.mock_single.nodes.report_node.node import mock_report_node

__all__ = ["mock_report_node"]
