"""Input model for final_report node."""

from __future__ import annotations

from pydantic import BaseModel

__all__ = ["FinalReportInput"]


class FinalReportInput(BaseModel):
    """Typed input for ``final_report``.

    Left empty; populated downstream.
    """

    pass
