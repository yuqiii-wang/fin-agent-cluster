"""Parent APIRouter — aggregates all domain sub-routers under ``/api/v1``."""

from __future__ import annotations

from fastapi import APIRouter

from backend.users.router import router as users_router
from backend.api.stream import router as stream_router
from backend.api.reports import router as reports_router
from backend.api.tasks import router as tasks_router
from backend.api.quant import router as quant_router

router = APIRouter(prefix="/api/v1")
router.include_router(users_router)
router.include_router(stream_router)
router.include_router(reports_router)
router.include_router(tasks_router)
router.include_router(quant_router)
