"""backend.users.queries — service layer for user query lifecycle.

Each module owns one lifecycle stage:

* :mod:`submit`  — ``submit_query``    – create/dedup and emit ``query_received``
* :mod:`ack`     — ``ack_query``       – ACK handshake, starts LangGraph execution
* :mod:`cancel`  — ``cancel_query``, ``cancel_node``, ``cancel_task_by_uuid``
* :mod:`pause`   — ``pause_query``     – set pause signal; graph pauses at next interrupt
* :mod:`resume`  — ``resume_query``    – resume from last LangGraph checkpoint (paused or cancelled)
* :mod:`status`  — ``get_query_status``, ``get_query_tasks``, ``get_node_executions``
* :mod:`threads` — ``list_threads``, ``get_thread_llm_responses``,
                   ``get_thread_state``, ``update_thread_status``,
                   ``emit_thread_event``, ``resync_thread``
"""

from __future__ import annotations

from backend.users.queries.submit import submit_query
from backend.users.queries.ack import ack_query
from backend.users.queries.cancel import cancel_query, cancel_node, cancel_task_by_uuid
from backend.users.queries.pause import pause_query
from backend.users.queries.resume import resume_query
from backend.users.queries.status import get_query_status, get_query_tasks, get_node_executions
from backend.users.queries.threads import (
    list_threads,
    get_thread_llm_responses,
    get_thread_state,
    update_thread_status,
    emit_thread_event,
    resync_thread,
)

__all__ = [
    "submit_query",
    "ack_query",
    "cancel_query",
    "cancel_node",
    "cancel_task_by_uuid",
    "pause_query",
    "resume_query",
    "get_query_status",
    "get_query_tasks",
    "get_node_executions",
    "list_threads",
    "get_thread_llm_responses",
    "get_thread_state",
    "update_thread_status",
    "emit_thread_event",
    "resync_thread",
]
