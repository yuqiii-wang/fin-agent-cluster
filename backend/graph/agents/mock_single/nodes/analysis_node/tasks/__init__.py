"""analysis_node.tasks — task functions for the mock_single analysis node.

Provides :func:`run_mock_analysis_task`, an opt-in streaming task that
generates mock tokens silently by default.  Tokens are pushed to Centrifugo
only when the user enables streaming via the API endpoint.
"""

from backend.graph.agents.mock_single.nodes.analysis_node.tasks.analysis import run_mock_analysis_task
from backend.graph.agents.mock_single.nodes.analysis_node.tasks.result import MockAnalysisResult

__all__ = ["run_mock_analysis_task", "MockAnalysisResult"]
