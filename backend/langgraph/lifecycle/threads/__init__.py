"""backend.langgraph.lifecycle.threads — thread-level lifecycle.

Public API
----------
:func:`register_thread`                      — register a new cancel token for the thread.
:func:`cancel_thread`                        — cascade cancel to all active nodes/tasks;
                                               persist DB; emit SSE.
:func:`complete_thread`                      — mark thread completed/failed; persist; emit SSE.
:func:`cancel_all_running_threads`           — shutdown handler; cancels everything in
                                               the process registry + orphaned DB rows.
:func:`pause_all_running_tasks_on_shutdown`  — shutdown handler; pauses running tasks so they
                                               are resumed via compact_and_continue on restart.
:func:`is_thread_cancelled`                  — check the in-process cancel token.
:func:`get_cancel_token`                     — retrieve the ``asyncio.Event`` for polling.

Implementation split
--------------------
sql.py  — SQL query constants
ops.py  — public API implementations
sse.py  — internal SSE helper functions
"""

from backend.langgraph.lifecycle.threads.ops import (
    cancel_all_running_threads,
    cancel_thread,
    complete_thread,
    get_cancel_token,
    is_thread_cancelled,
    pause_all_running_tasks_on_shutdown,
    register_thread,
)

__all__ = [
    "register_thread",
    "get_cancel_token",
    "is_thread_cancelled",
    "complete_thread",
    "cancel_thread",
    "cancel_all_running_threads",
    "pause_all_running_tasks_on_shutdown",
]
