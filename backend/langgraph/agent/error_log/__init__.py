"""backend.langgraph.agent.error_log -- per-thread WARNING+ log capture for recovery.

A bounded, deduplicated, Redis-backed store of a thread's recent error/warning
logs.  ``llm_orchestration_on_failure`` reads it (alongside the last failed task
output) to give the recovery LLM concrete diagnostic context without loading
every historical task output.
"""

from __future__ import annotations

from backend.langgraph.agent.error_log.context import (
    bind_log_thread_id,
    get_log_thread_id,
)
from backend.langgraph.agent.error_log.handler import (
    ThreadErrorLogHandler,
    start_listener,
    stop_listener,
)
from backend.langgraph.agent.error_log.models import ThreadLogEntry
from backend.langgraph.agent.error_log.store import get_thread_logs, record_thread_log

__all__ = [
    "ThreadErrorLogHandler",
    "ThreadLogEntry",
    "bind_log_thread_id",
    "get_log_thread_id",
    "get_thread_logs",
    "record_thread_log",
    "start_listener",
    "stop_listener",
]
