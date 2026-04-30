"""models — shared result types for streamer task functions."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass
class StreamTaskResult:
    """Structured result returned by a streamer task function.

    Attributes:
        pub_task_id:  DB row ID of the created ``fin_agents.tasks`` entry.
        produced:     Number of tokens written to ``fin:llm:tokens``.
        tps:          Observed tokens-per-second for the ingest run.
        result_str:   Human-readable summary stored in graph state.
    """

    pub_task_id: int
    produced: int
    tps: float
    result_str: str

    def as_node_output(self) -> dict:
        """Return a plain dict suitable for node execution log storage."""
        return {"total_tokens": self.produced, "tps": self.tps}


__all__ = ["StreamTaskResult"]
