"""tasks — task sub-packages for the merge_node pipeline stage.

Each child directory is a self-contained task with its own ``workflow.py``
(the async task function) and ``models.py`` (Pydantic I/O types).

Tasks
-----
merge   — aggregate news + stats into a single merged analysis dict.
"""

from backend.graph.agents._shared.nodes.merge_node.tasks.merge import run_merge_task

__all__ = ["run_merge_task"]
