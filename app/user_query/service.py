"""User query service — orchestrates graph execution and DB persistence."""

import logging
import uuid
from datetime import datetime

from sqlalchemy import select, update

from app.database import checkpointer, _get_session_factory
from app.graph.builder import build_graph
from app.models.agents import UserQuery
from app.schemas.requests import QueryRequest
from app.schemas.responses import QueryResponse

logger = logging.getLogger(__name__)


async def submit_query(request: QueryRequest) -> QueryResponse:
    """Submit a financial analysis query: persist, run graph, update status.

    Args:
        request: Query request body with query text and optional user_id.

    Returns:
        QueryResponse with thread_id, status, and generated report.

    Raises:
        Exception: Re-raised after persisting failure status to DB.
    """
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
        async with checkpointer() as cp:
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
                # query_understanding fills these
                "security_ticker": "",
                "security_name": "",
                "industry": "",
                "query_intent": "",
                "extra_context": {},
                # entity_resolution fills these
                "security_id": None,
                "entity_id": None,
                "entity_description": "",
                "entity_populated": False,
                # peer_discovery fills these
                "peers": {},
                "opposite_industry": "",
                "major_security": "",
                # analysis nodes fill these
                "market_data": "",
                "fundamental_analysis": "",
                "technical_analysis": "",
                "news_summary": "",
                "risk_assessment": "",
                "report": "",
                "steps": [],
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

    except Exception as e:
        logger.exception("Error processing query %s: %s", thread_id, e)
        async with _get_session_factory()() as session:
            stmt = (
                update(UserQuery)
                .where(UserQuery.thread_id == thread_id)
                .values(status="failed", error=str(e))
            )
            await session.execute(stmt)
            await session.commit()
        raise


async def get_query_by_thread(thread_id: str) -> UserQuery | None:
    """Retrieve a user query row by thread_id.

    Args:
        thread_id: UUID thread identifier.

    Returns:
        UserQuery ORM instance or None if not found.
    """
    factory = _get_session_factory()
    async with factory() as session:
        stmt = select(UserQuery).where(UserQuery.thread_id == thread_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
