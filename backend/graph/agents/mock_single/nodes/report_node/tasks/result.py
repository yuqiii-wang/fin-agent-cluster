"""Result model for the mock_single report task."""

from __future__ import annotations

from pydantic import BaseModel


class MockReportResult(BaseModel):
    """Return value from :func:`run_mock_report_task`.

    Attributes:
        pub_task_id:    Task UUID recorded in ``fin_agents.tasks``.
        task_id:        Task invocation UUID.
        produced:       Total number of tokens generated during the run.
        title:          Report title.
        recommendation: Trading recommendation (BUY / HOLD / SELL).
        confidence:     Confidence percentage (0-100).
        result_str:     Human-readable summary for the node output.
    """

    pub_task_id: str
    task_id: str
    produced: int
    title: str
    recommendation: str
    confidence: int
    result_str: str

    def as_node_output(self) -> dict:
        """Serialise to a dict suitable for storing in ``node_executions.output``.

        Returns:
            Dict with report-semantic keys for frontend display.
        """
        return {
            "title": self.title,
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "total_generated": self.produced,
            "summary": self.result_str,
        }


__all__ = ["MockReportResult"]
