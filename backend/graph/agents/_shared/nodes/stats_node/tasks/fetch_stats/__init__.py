"""fetch_stats — task sub-package for the stats fetch stage."""

from backend.graph.agents._shared.nodes.stats_node.tasks.fetch_stats.workflow import run_fetch_stats_task

__all__ = ["run_fetch_stats_task"]
