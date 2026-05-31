"""FastAPI router for system-level endpoints.

Mounted at ``/system`` under the parent API router:

    GET /api/v1/system/health  — aggregate health across all FastAPI instances
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter
from pydantic import BaseModel

from backend.config import get_settings
from backend.httpx_client import AsyncClient, make_internal_async_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["system"])


class InstanceHealth(BaseModel):
    """Health status of a single FastAPI instance."""

    url: str
    kind: str  # "runner"
    healthy: bool


class SystemHealthResponse(BaseModel):
    """Aggregate health status across all FastAPI instances."""

    all_healthy: bool
    total: int
    healthy_count: int
    instances: list[InstanceHealth]


async def _check_instance(client: AsyncClient, url: str, kind: str) -> InstanceHealth:
    """Probe a single instance's /health endpoint.

    Args:
        client: Shared async HTTP client.
        url:    Full URL including scheme and port, e.g. ``http://127.0.0.1:8432``.
        kind:   Instance role label (``"runner"``).

    Returns:
        :class:`InstanceHealth` with ``healthy=True`` when the probe returns
        HTTP 200 with ``{"status": "ok"}``, ``False`` on any error.
    """
    try:
        resp = await client.get(f"{url}/health", timeout=3.0)
        healthy = resp.status_code == 200 and resp.json().get("status") == "ok"
    except Exception:
        healthy = False
    return InstanceHealth(url=url, kind=kind, healthy=healthy)


class LlmProviderSettings(BaseModel):
    """Current LLM provider configuration."""

    provider: str
    model: str


class ServerSettingsResponse(BaseModel):
    """Current server-side settings exposed to the UI."""

    llm: LlmProviderSettings


@router.get("/settings", response_model=ServerSettingsResponse)
async def server_settings() -> ServerSettingsResponse:
    """Return current server settings (read-only, no auth required).

    Returns:
        :class:`ServerSettingsResponse` with the active LLM provider and model.
    """
    settings = get_settings()
    provider = (settings.LLM_PROVIDER or "mock").strip().lower()

    model_map: dict[str, str] = {
        "ollama": settings.OLLAMA_LLM_MODEL,
        "ark": settings.ARK_MODEL,
        "gemini": settings.GOOGLE_GEMINI_MODEL,
        "mock": "mock",
    }
    model = model_map.get(provider, "unknown")

    return ServerSettingsResponse(
        llm=LlmProviderSettings(provider=provider, model=model),
    )


@router.get("/health", response_model=SystemHealthResponse)
async def system_health() -> SystemHealthResponse:
    """Probe all configured FastAPI runner instances.

    Returns aggregate health so the frontend can wait until every instance
    is up before auto-triggering the E2E test.
    """
    settings = get_settings()

    runner_urls = [
        f"http://127.0.0.1:{settings.FASTAPI_PORT + i}"
        for i in range(settings.RUNNER_INSTANCE_COUNT)
    ]

    async with make_internal_async_client() as client:
        tasks = [
            *[_check_instance(client, url, "runner") for url in runner_urls],
        ]
        results: list[InstanceHealth] = await asyncio.gather(*tasks)

    healthy_count = sum(1 for r in results if r.healthy)
    return SystemHealthResponse(
        all_healthy=healthy_count == len(results),
        total=len(results),
        healthy_count=healthy_count,
        instances=results,
    )


