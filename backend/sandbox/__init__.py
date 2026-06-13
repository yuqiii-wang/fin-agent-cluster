"""Sandbox module -- safe, isolated execution of Python and bash scripts.

Execution runs inside Docker ``sandbox-runner-N`` containers.  Thread-ID
sharding routes every request for the same LangGraph thread to the same
container so files written by earlier tasks are visible to later tasks.

Isolation stack (container-side)
---------------------------------
1. **Docker network** -- containers run on both an ``internal: true`` network
   (for postgres-replica access) and the ``default`` network (for outbound
   internet access required by Playwright-driven Chromium).
2. **CWD confinement** -- subprocess CWD is ``/sandbox/{node_id}/`` inside the
   container; the security validator blocks ``../`` escapes.
3. **Resource limits** -- ``setrlimit`` caps RAM, CPU, processes, and FDs.
4. **Wall-clock timeout** -- hard kill via ``proc.communicate(timeout=N)``.
5. **Output cap** -- stdout/stderr truncated to ``SANDBOX_MAX_OUTPUT_BYTES``.
6. **Pre-execution validation** -- blocks obvious escape patterns on both the
   backend (early rejection) and inside the container (belt-and-suspenders).

Playwright support
------------------
Playwright (Chromium) is installed in the sandbox image.  LLM-generated
scripts produced by ``propose_playwright_script`` can use
``playwright.sync_api`` to navigate pages and return clean HTML to stdout.

Public API
----------
``execute_in_runner``    -- POST ``/execute`` on the correct runner shard.
``start_runner_session`` -- POST ``/session/{node_id}`` (raw shard call).
``end_runner_session``   -- DELETE ``/session/{node_id}`` (raw shard call).
``start_node_session``   -- lifecycle wrapper called by ``BaseNode.orchestrate``.
``end_node_session``     -- lifecycle wrapper called by ``BaseNode.orchestrate``.
``validate_script``      -- pre-execution security check (backend-side).
``SandboxInput``         -- low-level input model.
``SandboxResult``        -- low-level result model.
"""

from __future__ import annotations

from backend.sandbox.client import end_runner_session, execute_in_runner, start_runner_session
from backend.sandbox.models import SandboxInput, SandboxResult
from backend.sandbox.security import validate_script
from backend.sandbox.session import end_node_session, start_node_session

__all__ = [
    "execute_in_runner",
    "start_runner_session",
    "end_runner_session",
    "start_node_session",
    "end_node_session",
    "validate_script",
    "SandboxInput",
    "SandboxResult",
]
