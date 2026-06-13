"""Tasks package for prepare_index node.

Node-local tasks
----------------
``propose_index``  -- determines which equity market indexes to analyse
                     (hard-coded defaults + optional stock home index).

Shared task sequences used by this node are provided by the
``common_tasks`` library (``get_and_calculate_stats``).
"""

from backend.langgraph.nodes.prepare_index.tasks.propose_index import (
    propose_index,
    ProposeIndexInput,
    ProposeIndexOutput,
    IndexCandidate,
)

__all__: list[str] = [
    "propose_index",
    "ProposeIndexInput",
    "ProposeIndexOutput",
    "IndexCandidate",
]
