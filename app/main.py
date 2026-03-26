"""FastAPI application for financial agent cluster."""

import logging
from contextlib import asynccontextmanager
import uuid
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update

from app.database import init_db, get_checkpointer, close_checkpointer, _get_session_factory
from app.graph import build_graph
from app.models import UserQuery

logger = logging.getLogger(__name__)


class QueryRequest(BaseModel):
    query: str
    user_id: Optional[str] = None


class QueryResponse(BaseModel):
    thread_id: str
    status: str
    report: Optional[str] = None
    error: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage app startup and shutdown."""
    await init_db()
    yield


app = FastAPI(title="Financial Agent Cluster", version="1.0.0", lifespan=lifespan)


@app.post("/query", response_model=QueryResponse)
async def run_query(request: QueryRequest) -> QueryResponse:
    """Submit a financial analysis query and run the graph."""
    thread_id = str(uuid.uuid4())

    factory = _get_session_factory()
    async with factory() as session:
        user_query = UserQuery(
            thread_id=thread_id,
            user_id=request.user_id,
            query=request.query,
            status="running",
        )
        session.add(user_query)
        await session.commit()

    try:
        cp = await get_checkpointer()

        try:
            graph = build_graph().compile(checkpointer=cp)

            config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": "",
                }
            }

            initial_state = {
                "query": request.query,
                "thread_id": thread_id,
                "market_data": "",
                "fundamental_analysis": "",
                "technical_analysis": "",
                "risk_assessment": "",
                "report": "",
                "steps": []
            }

            final_state = await graph.ainvoke(initial_state, config)

            report = final_state.get("report", "No report generated")

            async with factory() as session:
                stmt = (
                    update(UserQuery)
                    .where(UserQuery.thread_id == thread_id)
                    .values(status="completed", answer=report, completed_at=datetime.utcnow())
                )
                await session.execute(stmt)
                await session.commit()

            return QueryResponse(
                thread_id=thread_id,
                status="completed",
                report=report,
            )

        finally:
            await close_checkpointer(cp)

    except Exception as e:
        logger.exception(f"Error processing query {thread_id}: {e}")
        async with _get_session_factory()() as session:
            stmt = (
                update(UserQuery)
                .where(UserQuery.thread_id == thread_id)
                .values(status="failed", error=str(e))
            )
            await session.execute(stmt)
            await session.commit()

        raise HTTPException(status_code=500, detail=str(e))


@app.get("/query/{thread_id}", response_model=QueryResponse)
async def get_query_status(thread_id: str) -> QueryResponse:
    """Get the status of a query by thread_id."""
    factory = _get_session_factory()
    async with factory() as session:
        stmt = select(UserQuery).where(UserQuery.thread_id == thread_id)
        result = await session.execute(stmt)
        query_row = result.scalar_one_or_none()

        if not query_row:
            raise HTTPException(status_code=404, detail="Query not found")

        return QueryResponse(
            thread_id=query_row.thread_id,
            status=query_row.status,
            report=None,
            error=query_row.error,
        )


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}
