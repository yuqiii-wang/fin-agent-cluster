"""Assistant API router — aggregates non-LangGraph sub-routers under ``/api/v1``.

Intentionally excludes:
- ``POST /users/query``              (submit — triggers LangGraph; runner only)
- ``POST /users/query/{id}/ack``     (ack   — starts graph run; runner only)

All other endpoints are included so assistant instances can serve reads and
control signals without competing with graph execution on runner instances.
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.api.auth import router as auth_router
from backend.api.centrifugo import router as centrifugo_router
from backend.api.stream import router as stream_router
from backend.api.tasks import router as tasks_router
from backend.api.threads import router as threads_router
from backend.assistant.queries import router as assistant_queries_router

router = APIRouter(prefix="/api/v1")
router.include_router(auth_router)
router.include_router(centrifugo_router)
router.include_router(stream_router)
router.include_router(tasks_router)
router.include_router(threads_router)
router.include_router(assistant_queries_router)
