"""FastAPI request schemas."""

from typing import Optional

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    """Request body for submitting a financial analysis query."""

    query: str = Field(..., description="The financial analysis question")
    user_id: Optional[str] = Field(None, description="Optional user identifier")
