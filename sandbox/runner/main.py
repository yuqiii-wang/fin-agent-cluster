"""Sandbox runner HTTP service.

This FastAPI application runs inside each ``sandbox-runner-N`` Docker
container.  It provides three endpoints:

``POST /session/{node_id}``
    Create the working directory for an agent node execution.
    Called by the backend before ``build_agent`` starts.

``DELETE /session/{node_id}``
    Recursively delete the working directory.
    Called by the backend after ``build_agent`` finishes (success or failure).

``POST /execute``
    Validate and execute a Python or bash script inside the node's workdir.
    All scripts from the same node execution share the same ``/sandbox/{node_id}/``
    directory so earlier tasks can write files that later tasks read.

``GET /health``
    Liveness probe consumed by the Docker healthcheck.

Isolation
---------
* Network — the container runs on an ``internal: true`` Docker network with
  no egress route to the internet.  No ``unshare --net`` is needed.
* Filesystem — CWD is pinned to ``/sandbox/{node_id}/``; the security
  validator in ``security.py`` blocks ``../`` escapes.
* Resources — ``setrlimit`` caps virtual memory, CPU, processes, and FDs
  inside the spawned subprocess.  Docker cgroup limits cap the container.
* Timeout — wall-clock limit applied via ``subprocess.communicate(timeout=N)``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from executor import execute_bash, execute_python
from security import validate_script

SANDBOX_DIR = Path("/sandbox")
SANDBOX_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="sandbox-runner", docs_url=None, redoc_url=None)


# ── Request / response models ──────────────────────────────────────────────────


class ExecuteRequest(BaseModel):
    """Payload for ``POST /execute``."""

    script: str
    language: str = "python"
    stdin: str = ""
    node_id: str = ""


# ── Endpoints ─────────────────────────────────────────────────────────────────


@app.post("/session/{node_id}", status_code=201)
def start_session(node_id: str) -> dict:
    """Create the sandbox workdir for *node_id*.

    Idempotent: if the directory already exists it is left as-is.

    Args:
        node_id: Agent node execution UUID.

    Returns:
        ``{"node_id": ..., "path": ...}``
    """
    work_dir = SANDBOX_DIR / node_id
    work_dir.mkdir(parents=True, exist_ok=True)
    return {"node_id": node_id, "path": str(work_dir)}


@app.delete("/session/{node_id}", status_code=200)
def end_session(node_id: str) -> dict:
    """Recursively delete the sandbox workdir for *node_id*.

    Args:
        node_id: Agent node execution UUID.

    Returns:
        ``{"deleted": True}``
    """
    work_dir = SANDBOX_DIR / node_id
    shutil.rmtree(work_dir, ignore_errors=True)
    return {"deleted": True}


@app.post("/execute")
async def execute(req: ExecuteRequest) -> dict:
    """Validate and execute a Python or bash script.

    Pre-execution security check runs inside the container as a belt-and-
    suspenders defence (the backend also validates before dispatching).
    The script runs inside ``/sandbox/{node_id}/`` with CWD confinement,
    resource limits, and a wall-clock timeout.

    Args:
        req: ``ExecuteRequest`` with script source, language, stdin, node_id.

    Returns:
        ``{stdout, stderr, exit_code, timed_out}`` dict.

    Raises:
        HTTPException 422: Language is unsupported or script fails validation.
    """
    if req.language not in ("python", "bash"):
        raise HTTPException(status_code=422, detail=f"Unsupported language: {req.language!r}")

    violation = validate_script(req.script, language=req.language)
    if violation:
        raise HTTPException(status_code=422, detail=f"Script rejected — {violation}")

    work_dir = SANDBOX_DIR / req.node_id if req.node_id else SANDBOX_DIR / "anon"
    work_dir.mkdir(parents=True, exist_ok=True)

    if req.language == "python":
        return await execute_python(req.script, stdin=req.stdin, work_dir=work_dir)
    return await execute_bash(req.script, stdin=req.stdin, work_dir=work_dir)


@app.get("/health")
def health() -> dict:
    """Liveness probe for Docker healthcheck."""
    return {"status": "ok"}
