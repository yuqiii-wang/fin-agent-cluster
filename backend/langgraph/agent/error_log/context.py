"""backend.langgraph.agent.error_log.context — current-thread binding for log capture.

The :class:`ContextVar` set here is read by :class:`ThreadErrorLogHandler` at
emit time so every WARNING+ log record produced inside a graph run (or a Celery
streaming task) can be tagged with the owning LangGraph ``thread_id`` without
threading the id through every call site.

Binding points
--------------
* Graph process — ``backend.main_thread.executor._run_graph`` binds the id right
  after stamping the fencing token, so all coroutines spawned by the graph
  inherit it (asyncio copies the context when creating sub-tasks).
* Celery worker — the streaming task entrypoints bind it before ``asyncio.run``
  so logs emitted while streaming carry the id in that process too.
"""

from __future__ import annotations

from contextvars import ContextVar

# The LangGraph thread_id that owns the current execution context, or None when
# running outside any graph run (e.g. plain HTTP request handling).
_log_thread_id: ContextVar[str | None] = ContextVar("log_thread_id", default=None)


def bind_log_thread_id(thread_id: str) -> None:
    """Bind *thread_id* to the current execution context for log capture.

    Args:
        thread_id: LangGraph thread UUID owning the current execution.
    """
    _log_thread_id.set(thread_id)


def get_log_thread_id() -> str | None:
    """Return the thread_id bound to the current context, or ``None``.

    Returns:
        The bound LangGraph thread UUID, or ``None`` outside a graph run.
    """
    return _log_thread_id.get()


__all__ = ["bind_log_thread_id", "get_log_thread_id"]
