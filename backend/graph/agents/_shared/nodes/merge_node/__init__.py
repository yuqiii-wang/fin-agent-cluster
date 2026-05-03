"""merge_node — shared fan-in node package.

Sub-modules
-----------
node    — :func:`merge_node` thin LangGraph node function.
models  — :class:`MergeNodeInput`, :class:`MergeNodeOutput` node-level I/O models.

Sub-packages
------------
tasks   — task functions and task-level models for this node.
"""

from backend.graph.agents._shared.nodes.merge_node.node import merge_node

__all__ = ["merge_node"]
