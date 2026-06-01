"""backend.db.postgres.lifecycle_status — canonical lifecycle status groupings.

Single source of truth for which statuses represent an **active** (in-flight)
lifecycle and which represent a **terminal** (ended) lifecycle, for both
thread-level (``query_status``) and node/task-level (``work_status``) enums.

Groupings
---------
Active (lifecycle started, work in progress):
    query_status : connecting | received | running
    work_status  : pending | running

Terminal (lifecycle ended, no further transitions):
    query_status : completed | failed | cancelled | wrong
    work_status  : completed | failed | cancelled | wrong

Note: ``paused`` is treated as **active** for work_status — the node is
paused awaiting user continue, and the task is retryable.

SQL helpers
-----------
``TERMINAL_QUERY_SQL`` and ``TERMINAL_WORK_SQL`` are pre-formatted SQL tuple
literals ready to embed in ``NOT IN (...)`` clauses so that raw SQL strings
throughout the codebase derive from the same source.
"""

from __future__ import annotations

from backend.db.postgres.types import QueryStatus, WorkStatus

# ---------------------------------------------------------------------------
# Thread-level (query_status)
# ---------------------------------------------------------------------------

#: Statuses meaning the thread has started and is still in progress.
ACTIVE_QUERY_STATUSES: frozenset[str] = frozenset(
    {QueryStatus.CONNECTING, QueryStatus.RECEIVED, QueryStatus.RUNNING}
)

#: Statuses meaning the thread has reached an end state.
TERMINAL_QUERY_STATUSES: frozenset[str] = frozenset(
    {QueryStatus.COMPLETED, QueryStatus.FAILED, QueryStatus.CANCELLED, QueryStatus.WRONG}
)

# SQL tuple literal for ``NOT IN`` / ``IN`` clauses — e.g.
#   WHERE status NOT IN {TERMINAL_QUERY_SQL}
TERMINAL_QUERY_SQL: str = "('completed', 'failed', 'cancelled', 'wrong')"
ACTIVE_QUERY_SQL: str = "('connecting', 'received', 'running')"

# ---------------------------------------------------------------------------
# Node / task level (work_status)
# ---------------------------------------------------------------------------

#: Statuses meaning the node/task has started and is still in progress.
#: ``paused`` is included because the node stays paused while a task is
#: awaiting user continue — no worker is processing it but the lifecycle has not ended.
ACTIVE_WORK_STATUSES: frozenset[str] = frozenset(
    {WorkStatus.PENDING, WorkStatus.RUNNING, WorkStatus.PAUSED}
)

#: Statuses meaning the node/task has reached an end state.
TERMINAL_WORK_STATUSES: frozenset[str] = frozenset(
    {WorkStatus.COMPLETED, WorkStatus.FAILED, WorkStatus.CANCELLED, WorkStatus.WRONG}
)

# SQL tuple literals for ``NOT IN`` / ``IN`` clauses.
TERMINAL_WORK_SQL: str = "('completed', 'failed', 'cancelled', 'wrong')"
ACTIVE_WORK_SQL: str = "('pending', 'running', 'paused')"

__all__ = [
    "ACTIVE_QUERY_STATUSES",
    "TERMINAL_QUERY_STATUSES",
    "TERMINAL_QUERY_SQL",
    "ACTIVE_QUERY_SQL",
    "ACTIVE_WORK_STATUSES",
    "TERMINAL_WORK_STATUSES",
    "TERMINAL_WORK_SQL",
    "ACTIVE_WORK_SQL",
]
