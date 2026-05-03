"""query_node — shared query-parser node package.

Sub-modules
-----------
node    — :func:`query_node` thin LangGraph node function.
models  — :class:`QueryNodeInput`, :class:`QueryNodeOutput` node-level I/O models.

Sub-packages
------------
tasks   — task functions and task-level models for this node.
"""

from backend.graph.agents._shared.nodes.query_node.node import query_node

__all__ = ["query_node"]
