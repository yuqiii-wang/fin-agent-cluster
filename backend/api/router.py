"""Parent APIRouter — aggregates all domain sub-routers under ``/api/v1``."""

from __future__ import annotations

from fastapi import APIRouter

from backend.api.auth.router import router as auth_router
from backend.api.queries.router import router as users_router
from backend.api.stream.router import router as stream_router
from backend.api.system.router import router as system_router
from backend.api.tasks.router import router as tasks_router
from backend.api.threads.router import router as threads_router

router = APIRouter(prefix="/api/v1")
router.include_router(auth_router)
router.include_router(users_router)
router.include_router(stream_router)
router.include_router(system_router)
router.include_router(tasks_router)
router.include_router(threads_router)
