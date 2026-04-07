"""FastAPI application for financial agent cluster."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db
from app.user_query.routes import router as query_router
from app.routes.health import router as health_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage app startup and shutdown."""
    await init_db()
    yield


app = FastAPI(title="Financial Agent Cluster", version="1.0.0", lifespan=lifespan)
app.include_router(query_router)
app.include_router(health_router)
