"""User query endpoints — submit and retrieve financial analysis queries."""

import logging

from fastapi import APIRouter, HTTPException

from app.schemas.requests import QueryRequest
from app.schemas.responses import QueryResponse
from app.user_query.service import submit_query, get_query_by_thread

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/query", response_model=QueryResponse)
async def run_query(request: QueryRequest) -> QueryResponse:
    """Submit a financial analysis query and run the LangGraph workflow.

    Args:
        request: Query request body with query text and optional user_id.

    Returns:
        QueryResponse with thread_id, status, and generated report.
    """
    try:
        return await submit_query(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/query/{thread_id}", response_model=QueryResponse)
async def get_query_status(thread_id: str) -> QueryResponse:
    """Get the status of a query by thread_id.

    Args:
        thread_id: UUID thread identifier.

    Returns:
        QueryResponse with current status.
    """
    query_row = await get_query_by_thread(thread_id)
    if not query_row:
        raise HTTPException(status_code=404, detail="Query not found")

    return QueryResponse(
        thread_id=query_row.thread_id,
        status=query_row.status,
        report=None,
        error=query_row.error,
    )
