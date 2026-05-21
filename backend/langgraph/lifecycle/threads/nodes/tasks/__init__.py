"""backend.langgraph.lifecycle.threads.nodes.tasks — task-level lifecycle.

Public API
----------
:func:`create_task`              — INSERT a task row (status=running); emit SSE.
:func:`complete_task`            — UPDATE to completed/failed; emit SSE.
:func:`persist_task_result`      — Write terminal state to DB only (no SSE).
:func:`cancel_task`              — UPDATE to cancelled; revoke Celery job; emit SSE.
:func:`get_existing_task_for_node` — Find any existing task for a node+task_name (used for retry dedup).
:func:`get_paused_task_for_node` — Find paused task for a node+task_name on graph resume.
:func:`reset_task_for_retry`     — Reset terminal → running for retry; emit SSE.
:func:`get_task_full`            — Fetch task + execution input from DB.
:func:`get_latest_llm_response`  — Fetch latest LLM response thinking/answer for a task.

Implementation split
--------------------
sql.py       — SQL query constants
sse.py       — internal SSE helper function
ops.py       — thin public API shim (re-exports from ops_utils/)
ops_utils/   — focused implementation modules:
    create.py       — create_task
    complete.py     — complete_task, persist_task_result
    cancel_pause.py — cancel_task, pause_task, cleanup_zombie_tasks
    retry.py        — reset_task_for_retry
    queries.py      — read-only query helpers
"""

from backend.langgraph.lifecycle.threads.nodes.tasks.ops import (
    cancel_task,
    cleanup_zombie_tasks,
    complete_task,
    create_task,
    get_existing_task_for_node,
    get_latest_llm_response,
    get_paused_task_for_node,
    get_task_full,
    pause_task,
    persist_task_result,
    reset_task_for_retry,
)

__all__ = [
    "cancel_task",
    "cleanup_zombie_tasks",
    "complete_task",
    "create_task",
    "get_existing_task_for_node",
    "get_latest_llm_response",
    "get_paused_task_for_node",
    "get_task_full",
    "pause_task",
    "persist_task_result",
    "reset_task_for_retry",
]
