"""final_report package -- Terminal Workflow node that assembles the final report."""

from backend.langgraph.nodes.final_report.node import final_report_node
from backend.langgraph.nodes.final_report.models import (
    FinalReportInput,
    FinalReportOutput,
)

__all__ = [
    "final_report_node",
    "FinalReportInput",
    "FinalReportOutput",
]
