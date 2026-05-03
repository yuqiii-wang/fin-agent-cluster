"""models — shared result types for mock agent task functions."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass
class MockTaskResult:
    """Structured result returned by a mock agent task function.

    Attributes:
        pub_task_id:  UUID of the created ``fin_agents.tasks`` entry (PK).
        task_id:    Task invocation UUID (task-level identity).
        produced:     Number of tokens written to ``fin:llm:tokens``.
        tps:          Observed tokens-per-second for the ingest run.
        result_str:   Human-readable summary stored in graph state.
    """

    pub_task_id: str
    task_id: str
    produced: int
    tps: float
    result_str: str

    def as_node_output(self) -> dict:
        """Return a plain dict suitable for node execution log storage."""
        return {"total_tokens": self.produced, "tps": self.tps, "task_id": self.task_id}


__all__ = ["MockTaskResult"]
