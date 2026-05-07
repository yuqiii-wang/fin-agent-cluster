"""Result model for the mock_single analysis task."""

from __future__ import annotations

from pydantic import BaseModel


class MockAnalysisResult(BaseModel):
    """Return value from :func:`run_mock_analysis_task`.

    Attributes:
        pub_task_id:  Task UUID recorded in ``fin_agents.tasks``.
        task_id:      Task invocation UUID.
        produced:     Total number of tokens generated during the run.
        result_str:   Human-readable summary for the node output.
    """

    pub_task_id: str
    task_id: str
    produced: int
    result_str: str

    def as_node_output(self) -> dict:
        """Serialise to a dict suitable for storing in ``node_executions.output``.

        Returns:
            Dict with analysis-semantic keys for frontend display.
        """
        return {
            "total_generated": self.produced,
            "summary": self.result_str,
        }


__all__ = ["MockAnalysisResult"]
