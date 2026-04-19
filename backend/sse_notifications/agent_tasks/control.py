"""Task control signals — in-process cancel / pass signalling for streaming tasks.

The streaming loops in :mod:`backend.sse_notifications.agent_tasks.token_stream`
check for pending control signals at the start of each token iteration.
API endpoints write signals via :func:`signal_task_control`; the streaming
loops consume and clear them.

Signals are intentionally ephemeral (in-process dict) — they are only needed
while the streaming loop is active.  Persistence is unnecessary because the
actual status change is committed to the DB by the lifecycle emitters.
"""

from __future__ import annotations

from typing import Literal

# ---------------------------------------------------------------------------
# Control action type
# ---------------------------------------------------------------------------

TaskControlAction = Literal["cancel", "pass"]

# Maps task_id → pending control action.
# Written by API endpoints; consumed (and deleted) by streaming loops.
_task_signals: dict[int, str] = {}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TaskCancelledSignal(Exception):
    """Raised inside a streaming loop when the client cancels the task."""


class TaskPassSignal(Exception):
    """Raised inside a streaming loop when the client accepts partial output.

    Attributes:
        partial_text: Tokens accumulated before the pass signal arrived.
    """

    def __init__(self, partial_text: str) -> None:
        """Store the partial output accumulated so far.

        Args:
            partial_text: Tokens collected up to the point of the signal.
        """
        self.partial_text = partial_text
        super().__init__(partial_text)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def signal_task_control(task_id: int, action: TaskControlAction) -> None:
    """Register a control signal for a currently-streaming task.

    The next iteration of :func:`~backend.sse_notifications.agent_tasks.token_stream.stream_text_task`
    or :func:`~backend.sse_notifications.agent_tasks.token_stream.stream_llm_task` for
    *task_id* will raise :class:`TaskCancelledSignal` or
    :class:`TaskPassSignal` and stop the upstream generator.

    Args:
        task_id: DB primary key of the running task.
        action:  ``"cancel"`` to abort, ``"pass"`` to accept partial output.
    """
    _task_signals[task_id] = action


def _check_signal(task_id: int, parts: list[str]) -> None:
    """Consume a pending control signal and raise the matching exception.

    Args:
        task_id: DB primary key of the task being streamed.
        parts:   Tokens accumulated so far (used for the pass signal).

    Raises:
        TaskCancelledSignal: When the pending action is ``"cancel"``.
        TaskPassSignal:      When the pending action is ``"pass"``.
    """
    action = _task_signals.pop(task_id, None)
    if action == "cancel":
        raise TaskCancelledSignal()
    if action == "pass":
        raise TaskPassSignal("".join(parts))


__all__ = [
    "TaskControlAction",
    "TaskCancelledSignal",
    "TaskPassSignal",
    "signal_task_control",
    "_check_signal",
    "_task_signals",
]
