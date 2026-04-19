"""Celery streaming workers — batch-consume Redis Stream topics via consumer groups.

Workers
-------
graph_events  — ``fin:graph:events``   analytics / dead-letter logging
market_data   — ``fin:market:ticks``   aggregate stats, DB upsert
signals       — ``fin:signals:trade``  risk checks, strategy logging

Graph execution (``graph_runner``) runs as an ``asyncio.Task`` on the FastAPI
event loop — not a Celery task.
"""

__all__ = ["graph_events", "market_data", "signals"]
