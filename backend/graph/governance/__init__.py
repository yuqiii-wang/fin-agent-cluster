"""graph.governance — execution hierarchy registry and lifecycle publisher.

Tracks the four-level execution tree for every LangGraph thread in Redis
and provides a publisher that emits terminal lifecycle events to all live
leaf streams when a thread ends or is cancelled.

Hierarchy
---------
::

    thread_id  (top-level — LangGraph thread / user query)
      └─ node_id   (LangGraph node execution)
           └─ task_id  (task invocation within the node)
                └─ stream_id  (optional LLM token stream)

Each level has independent status tracking and cancel signals so that
cancellation can be scoped to thread, node, or individual task.
"""

from backend.graph.governance.registry import (
    deregister_stream,
    get_streams_for_task,
    get_streams_for_thread,
    get_tasks_for_node,
    get_node_status,
    get_task_status,
    register_stream,
    request_node_cancel,
    request_task_cancel,
    check_node_cancel,
    check_task_cancel,
    set_thread_status,
    set_node_status,
    set_task_status,
    close_governed_ids,
)
from backend.graph.governance.publisher import (
    publish_governance_end,
    publish_node_cancel,
    publish_task_cancel,
)

__all__ = [
    # hierarchy
    "register_stream",
    "deregister_stream",
    "get_streams_for_task",
    "get_tasks_for_node",
    "get_streams_for_thread",
    # per-level status
    "set_thread_status",
    "set_node_status",
    "get_node_status",
    "set_task_status",
    "get_task_status",
    # cancel signals
    "request_node_cancel",
    "check_node_cancel",
    "request_task_cancel",
    "check_task_cancel",
    # cascade close
    "close_governed_ids",
    # lifecycle publisher
    "publish_governance_end",
    "publish_node_cancel",
    "publish_task_cancel",
]
