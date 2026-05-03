"""task — SSE notifications for agent task-level lifecycle events.

Third level of the event scope hierarchy (thread → node → task → stream).

Sub-modules
-----------
notifications  — task CRUD lifecycle (create / complete / fail / cancel).
ack            — task-step delivery tracking via Redis ACK store.
control        — in-process cancel / pass signal handling for streaming tasks.
token_stream   — Redis Streams token publishing for live LLM output.
"""

from backend.sse_notifications.task.notifications import (
    cancel_task,
    complete_task,
    create_task,
    fail_task,
)
from backend.sse_notifications.task.ack import (
    ack_task_step,
    increment_task_step_retry,
)
from backend.sse_notifications.task.control import (
    TaskCancelledSignal,
    TaskControlAction,
    TaskPassSignal,
    _check_signal,
    _task_signals,
    signal_task_control,
)
from backend.sse_notifications.task.token_stream import (
    stream_llm_task,
    stream_text_task,
)

__all__ = [
    # lifecycle
    "create_task",
    "complete_task",
    "fail_task",
    "cancel_task",
    # ack / retry tracking
    "ack_task_step",
    "increment_task_step_retry",
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
]
