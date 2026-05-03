"""merge — task sub-package for the merge aggregation stage.

Re-exports the public API so callers can import directly from this package.
"""

from backend.graph.agents._shared.nodes.merge_node.tasks.merge.workflow import run_merge_task

__all__ = ["run_merge_task"]
