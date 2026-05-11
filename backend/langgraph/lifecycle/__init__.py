"""backend.langgraph.lifecycle — thread / node / task lifecycle management.

Hierarchy
---------
Thread (thread_id)
  └── Node  (node_id = make_node_id(thread_id, node_name))
        └── Task  (task_id = make_task_id())

Cancellation propagation
------------------------
``cancel_thread``
  → revoke all in-flight Celery tasks for the thread
  → bulk-cancel all active tasks  (DB RETURNING → SSE)
  → bulk-cancel all active nodes  (DB RETURNING → SSE)
  → cancel thread row             (DB RETURNING → SSE)
  → set asyncio cancel token      (signals delegation poll loops)

``cancel_node``
  → revoke Celery tasks for the node
  → bulk-cancel active tasks for the node
  → cancel the node itself

``cancel_task``
  → revoke the specific Celery task
  → cancel the task row

Terminal states (no further transitions allowed)
------------------------------------------------
work_status  : completed | failed | cancelled | wrong
query_status : completed | failed | cancelled

SSE guarantee
-------------
Every SSE publish is preceded by a DB write.  If the publish fails the DB
state is still correct; the UI can recover via polling.

Process shutdown
----------------
Call ``cancel_all_running_threads(reason="shutdown")`` from the FastAPI
lifespan shutdown handler.  It signals all locally-tracked threads and does
a best-effort bulk update for orphaned DB rows.
"""

from __future__ import annotations

from backend.langgraph.lifecycle.ids import make_node_id, make_task_id
from backend.langgraph.lifecycle.errors import ThreadCancelledError
from backend.langgraph.lifecycle.threads import (
    cancel_all_running_threads,
    cancel_thread,
    complete_thread,
    get_cancel_token,
    is_thread_cancelled,
    register_thread,
)
from backend.langgraph.lifecycle.threads.nodes import (
    cancel_node,
    complete_node,
    upsert_node,
)
from backend.langgraph.lifecycle.threads.nodes.tasks import (
    cancel_task,
    complete_task,
    create_task,
    persist_task_result,
)

__all__ = [
    # ID helpers
    "make_node_id",
    "make_task_id",
    # Exception type
    "ThreadCancelledError",
    # Thread-level
    "register_thread",
    "get_cancel_token",
    "is_thread_cancelled",
    "complete_thread",
    "cancel_thread",
    "cancel_all_running_threads",
    # Node-level
    "upsert_node",
    "complete_node",
    "cancel_node",
    # Task-level
    "create_task",
    "complete_task",
    "persist_task_result",
    "cancel_task",
]
