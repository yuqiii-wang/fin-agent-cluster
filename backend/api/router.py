"""Parent APIRouter — aggregates all domain sub-routers under ``/api/v1``."""

from __future__ import annotations

from fastapi import APIRouter

from backend.api.auth import router as auth_router
from backend.api.centrifugo import router as centrifugo_router
from backend.api.queries import router as users_router
from backend.api.stream import router as stream_router
from backend.api.tasks import router as tasks_router
from backend.api.threads import router as threads_router

router = APIRouter(prefix="/api/v1")
router.include_router(auth_router)
router.include_router(centrifugo_router)
router.include_router(users_router)
router.include_router(stream_router)
router.include_router(tasks_router)
router.include_router(threads_router)
