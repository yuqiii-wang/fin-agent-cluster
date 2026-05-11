"""backend.main_thread — in-process graph execution for main thread FastAPI instances.

This package replaces the standalone ``graph_runner`` subprocess.  Each
FastAPI (main thread) instance owns its graph coroutines directly on uvicorn's
asyncio event loop.

Thread ownership is tracked via a Redis lock (``fin:thread:lock:{thread_id}``)
so that exactly one main thread handles each graph run at any time.

Public API
----------
:func:`dispatch_graph_run`  — acquire lock and dispatch graph as asyncio.Task.
:exc:`ThreadRoutingError`   — raised when another live instance owns the thread.
:func:`recover_running_threads` — call on startup to resume orphaned runs.
:func:`wait_all`            — call on shutdown to drain in-flight graph tasks.
"""

from backend.main_thread.executor import ThreadRoutingError, dispatch_graph_run
from backend.main_thread.registry import wait_all
from backend.main_thread.startup import recover_running_threads

__all__ = [
    "ThreadRoutingError",
    "dispatch_graph_run",
    "recover_running_threads",
    "wait_all",
]
