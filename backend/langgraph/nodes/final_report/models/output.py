"""Output model for final_report node."""

from __future__ import annotations

from pydantic import BaseModel

__all__ = ["FinalReportOutput"]


class FinalReportOutput(BaseModel):
    """Typed output for ``final_report``.

    Left empty; populated downstream.
    """

    pass
