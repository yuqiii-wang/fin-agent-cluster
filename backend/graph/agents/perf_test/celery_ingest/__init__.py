"""PerfIngest Celery application package.

Provides the dedicated Celery app and tasks for bulk-writing mock tokens
to per-session ``fin:perf:{thread_id}`` Redis streams during performance
testing.  Isolated from the main :mod:`backend.streaming` Celery app via
separate Redis DB indices (broker DB 3, backend DB 4).

Imports are intentionally deferred — the Celery app is only created when
a perf test is triggered, not at FastAPI startup.  Import explicitly when
needed::

    from backend.graph.agents.perf_test.celery_ingest.celery_app import perf_ingest_app
    from backend.graph.agents.perf_test.celery_ingest.tasks import bulk_ingest_stream
"""

__all__ = [
    "perf_ingest_app",
    "bulk_ingest_stream",
    "recover_stalled_streams",
]

