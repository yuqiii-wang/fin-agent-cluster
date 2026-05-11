"""backend.main_thread.context — per-graph-run ContextVars.

Values set here propagate automatically to all coroutines and async tasks
spawned within the same asyncio.Task that runs the LangGraph graph.  This
includes inner sub-tasks created by LangGraph's internal machinery, since
Python asyncio copies the current context when creating a new Task.

Usage pattern
-------------
At the start of ``_run_graph``:

    from backend.main_thread.context import set_fencing_token
    set_fencing_token(acquired_token)

Deep inside lifecycle write calls (upsert_node, create_task, …):

    from backend.main_thread.context import get_fencing_token
    token = get_fencing_token()  # returns the token set by the owning graph run
"""

from __future__ import annotations

from contextvars import ContextVar

# Fencing token for the current graph run.  Incremented atomically in Redis
# on every lock acquisition or steal.  Zombie writers hold an older (smaller)
# token; DB guards reject their writes by comparing the token in every write.
# Default 0 means "no active graph run" — treated as older than any real token.
_fencing_token: ContextVar[int] = ContextVar("fencing_token", default=0)


def set_fencing_token(token: int) -> None:
    """Store the fencing token for this graph-run context.

    Must be called once at the start of ``_run_graph`` before any lifecycle
    writes are made.

    Args:
        token: Fencing token returned by :func:`~backend.main_thread.lock.acquire_lock`
            or :func:`~backend.main_thread.lock.steal_lock`.
    """
    _fencing_token.set(token)


def get_fencing_token() -> int:
    """Return the fencing token for this graph-run context.

    Returns 0 when called outside a graph run (e.g. from a Celery worker),
    which is intentional — Celery workers do not need fencing because their
    task rows are addressed by unique UUID task_id.

    Returns:
        Fencing token integer (>= 1 inside an active graph run, 0 otherwise).
    """
    return _fencing_token.get()


__all__ = ["set_fencing_token", "get_fencing_token"]
