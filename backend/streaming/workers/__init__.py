"""Celery streaming workers — batch-consume Redis Stream topics via consumer groups.

Workers
-------
graph_events  — ``fin:graph:events``   analytics / dead-letter logging
market_data   — ``fin:market:ticks``   aggregate stats, DB upsert
signals       — ``fin:signals:trade``  risk checks, strategy logging

Graph execution (``backend.graph.runner.run_graph_task``) is dispatched via
Celery per-thread queues so each query is isolated; no two queries share a
worker slot.  The runner lives in ``backend/graph/runner.py`` and is included
in the Celery worker via ``celery_app.py``.
"""

__all__ = ["graph_events", "market_data", "signals"]
