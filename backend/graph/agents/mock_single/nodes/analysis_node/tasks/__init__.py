"""analysis_node.tasks — task functions for the mock_single analysis node.

The concurrency ingest task is the shared Celery-based implementation from
``mock_perf``.  Importing it here keeps ``node.py`` free of cross-agent
import paths.
"""

from backend.graph.agents.mock_perf.tasks.concurrency import run_concurrency_task

__all__ = ["run_concurrency_task"]
