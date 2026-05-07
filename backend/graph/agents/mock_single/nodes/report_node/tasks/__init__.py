"""report_node.tasks — task functions for the mock_single report node.

Provides :func:`run_mock_report_task`, an opt-in streaming task that
generates mock trading signal report tokens silently by default.  Tokens
are pushed to Centrifugo only when the user enables streaming via the API
endpoint.
"""

from backend.graph.agents.mock_single.nodes.report_node.tasks.report import run_mock_report_task
from backend.graph.agents.mock_single.nodes.report_node.tasks.result import MockReportResult

__all__ = ["run_mock_report_task", "MockReportResult"]
