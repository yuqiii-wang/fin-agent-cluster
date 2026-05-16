"""backend.langgraph.lifecycle.errors — lifecycle error codes and exception types."""

from __future__ import annotations

from backend.langgraph.lifecycle.errors.codes import (
    LIFECYCLE_ALREADY_TERMINAL,
    LIFECYCLE_CANCEL_FAILED,
    LIFECYCLE_CHECKPOINT_NOT_FOUND,
    LIFECYCLE_DB_ERROR,
    LIFECYCLE_NODE_NOT_FOUND,
    LIFECYCLE_REEXPLORE_FAILED,
    LIFECYCLE_SSE_ERROR,
    LIFECYCLE_TASK_NOT_FOUND,
    LIFECYCLE_THREAD_NOT_FOUND,
)


class ThreadCancelledError(RuntimeError):
    """Raised inside a LangGraph task when the thread's cancel token is set.

    This is an ``Exception`` (not ``BaseException``) so existing
    ``except Exception`` handlers in node functions catch it and call
    ``complete_task(failed=True)``.  ``complete_task`` is idempotent on
    already-terminal tasks, so the handler is a safe no-op.
    """

    def __init__(self, thread_id: str) -> None:
        super().__init__(f"Thread '{thread_id}' was cancelled")
        self.thread_id = thread_id


class NodeCancelledError(RuntimeError):
    """Raised when a specific node is cancelled externally (API ``cancel_node``).

    Detected by polling a per-node Redis cancel flag inside ``_await_result``.
    ``BaseNode.__call__`` catches this and returns a ``cancelled`` state delta
    instead of re-raising, so the other parallel branches continue unaffected.
    """

    def __init__(self, node_id: str) -> None:
        super().__init__(f"Node '{node_id}' was cancelled")
        self.node_id = node_id


__all__ = [
    "LIFECYCLE_THREAD_NOT_FOUND",
    "LIFECYCLE_NODE_NOT_FOUND",
    "LIFECYCLE_TASK_NOT_FOUND",
    "LIFECYCLE_ALREADY_TERMINAL",
    "LIFECYCLE_CANCEL_FAILED",
    "LIFECYCLE_DB_ERROR",
    "LIFECYCLE_SSE_ERROR",
    "LIFECYCLE_CHECKPOINT_NOT_FOUND",
    "LIFECYCLE_REEXPLORE_FAILED",
    "NodeCancelledError",
    "ThreadCancelledError",
]
