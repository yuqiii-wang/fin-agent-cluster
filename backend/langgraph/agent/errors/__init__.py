"""backend.langgraph.agent.errors — agent error codes and exception types."""

from __future__ import annotations

from backend.langgraph.agent.errors.codes import (
    AGENT_COMPACT_TOO_FEW_ENTRIES,
    AGENT_MAX_ITERATIONS,
    AGENT_MEMORY_NOT_FOUND,
    AGENT_NOT_RUNNING,
    AGENT_PAUSE_ALREADY_SET,
    AGENT_SKILL_NOT_FOUND,
    AGENT_STATE_NOT_FOUND,
)
from backend.langgraph.lifecycle.errors import TaskPausedError


class AgentPausedError(TaskPausedError):
    """Raised by the custom agent loop when the agent-level Redis pause flag is detected.

    Subclasses ``TaskPausedError`` so ``executor.py`` treats it identically —
    graceful exit without marking the thread as failed.  The owning node is
    transitioned to ``paused`` via ``pause_node`` before this exception reaches
    the executor.

    Attributes:
        node_id:     UUID of the paused agent node.
        auto_resume: When ``True``, ``EntrypointMixin`` schedules an automatic
                     ``resume_query`` background task after ``pause_node``
                     completes, so the agent continues seamlessly once the
                     context update (new skill / memory compaction) is saved.
    """

    def __init__(self, node_id: str, *, auto_resume: bool = False) -> None:
        super().__init__(task_id=node_id)
        self.node_id = node_id
        self.auto_resume = auto_resume


__all__ = [
    "AGENT_COMPACT_TOO_FEW_ENTRIES",
    "AGENT_MAX_ITERATIONS",
    "AGENT_MEMORY_NOT_FOUND",
    "AGENT_NOT_RUNNING",
    "AGENT_PAUSE_ALREADY_SET",
    "AGENT_SKILL_NOT_FOUND",
    "AGENT_STATE_NOT_FOUND",
    "AgentPausedError",
]
