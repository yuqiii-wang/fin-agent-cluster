"""agent_tasks — SSE notifications for agent task lifecycle, control and token streaming.

Re-exports the full public API from the three sub-modules so callers can
import from either the sub-package or the top-level ``sse_notifications``.
"""

from backend.sse_notifications.agent_tasks.control import (
    TaskCancelledSignal,
    TaskControlAction,
    TaskPassSignal,
    _check_signal,
    _task_signals,
    signal_task_control,
)
from backend.sse_notifications.agent_tasks.lifecycle import (
    cancel_task,
    complete_task,
    create_task,
    emit_done,
    fail_task,
)
from backend.sse_notifications.agent_tasks.token_stream import (
    stream_llm_task,
    stream_perf_text_task,
    stream_text_task,
)

__all__ = [
    # lifecycle
    "create_task",
    "complete_task",
    "fail_task",
    "cancel_task",
    "emit_done",
    # control
    "TaskControlAction",
    "TaskCancelledSignal",
    "TaskPassSignal",
    "signal_task_control",
    "_check_signal",
    "_task_signals",
    # token streaming
    "stream_llm_task",
    "stream_text_task",
    "stream_perf_text_task",
]
