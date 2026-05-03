"""analysis_node — LLM ingest/digest node package for the mock single-request pipeline.

Sub-modules
-----------
node    — :func:`mock_analysis_node` thin LangGraph node function.

Sub-packages
------------
tasks   — task functions for this node (throughput ingest via Celery).
"""

from backend.graph.agents.mock_single.nodes.analysis_node.node import mock_analysis_node

__all__ = ["mock_analysis_node"]
