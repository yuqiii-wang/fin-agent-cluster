"""Assistant FastAPI application package.

Provides a lightweight FastAPI instance that handles non-LangGraph requests:
- Query status reads, cancellation, and metadata
- Auth, Centrifugo token, reports, tasks, quant, threads
- Status verifier background task: re-delivers unACKed query-status phases

Does **not** compile LangGraph, start Celery fallback workers, or run a
cancel-signal listener.  All those responsibilities belong to the runner
instances (``backend.main``).

Public exports:
    app   — the assistant FastAPI application instance
"""

from __future__ import annotations

from backend.assistant.main import app

__all__ = ["app"]
