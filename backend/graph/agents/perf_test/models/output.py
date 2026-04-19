"""PerfTestOutput — structured result for the perf_test_streamer node."""

from __future__ import annotations

from pydantic import BaseModel


class PerfTestOutput(BaseModel):
    """Output produced by the :func:`~backend.graph.agents.perf_test.node.perf_test_streamer` node.

    Attributes:
        total_tokens: Number of tokens streamed.
        tps:          Achieved throughput in tokens per second.
    """

    total_tokens: int
    tps: float


__all__ = ["PerfTestOutput"]
