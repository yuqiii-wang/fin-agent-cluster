"""FastAPI response schemas."""

from typing import Optional

from pydantic import BaseModel, Field


class QueryResponse(BaseModel):
    """Response body for a financial analysis query."""

    thread_id: str
    status: str
    report: Optional[str] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
