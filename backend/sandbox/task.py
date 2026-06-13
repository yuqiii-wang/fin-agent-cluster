"""run_sandbox -- NodeTask: execute LLM-generated Python or bash inside an isolated sandbox.

The LLM writes a self-contained script (Python or bash) to process text
input (e.g. web-scraped markdown CSV -> JSON) and this task runs it safely.

Execution layers
----------------
LangGraph layer (``_run_sandbox_task`` decorated with ``@task``):
    Creates the DB task row, delegates to the Celery completion worker, and
    returns a :class:`~backend.langgraph.models.models.TaskOutput`.

Celery layer (``_handler``):
    1. Validates the script with :func:`~backend.sandbox.security.validate_script`
       (blocks path traversal, sensitive paths, network imports).
    2. Creates an isolated temp dir via :func:`~backend.sandbox.environment.sandbox_workdir`.
    3. Dispatches to :func:`~backend.sandbox.executor.execute_python` or
       :func:`~backend.sandbox.executor.execute_bash` as appropriate.
    4. Returns serialised :class:`~backend.sandbox.models.SandboxResult`.

Isolation guarantees
--------------------
* **Network** -- ``unshare --net`` creates a new Linux network namespace; all
  socket operations fail regardless of the script content.
* **Filesystem** -- the process CWD is pinned to a temp dir deleted on exit;
  path-traversal patterns are rejected at the validation stage.
* **Resources** -- ``setrlimit`` caps virtual memory, CPU time, child-process
  count, and open-file descriptors as configured in ``Settings``.
* **Timeout** -- wall-clock cap via ``subprocess.communicate(timeout=N)``
  with ``proc.kill()`` on expiry.

Public exports
--------------
``run_sandbox``      -- :class:`~backend.langgraph.models.task.NodeTask` instance.
``RunSandboxInput``  -- Pydantic input model.
``RunSandboxOutput`` -- Pydantic output model.
``HANDLERS``         -- dict slice for registration in
                       ``backend.langgraph.nodes.HANDLERS``.
"""

from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask
from backend.sandbox.errors import SandboxSecurityError, SandboxTimeoutError, SandboxSpawnError
from backend.sandbox.errors.codes import (
    SANDBOX_SECURITY_VIOLATION,
    SANDBOX_TIMEOUT,
    SANDBOX_SPAWN_ERROR,
)

logger = logging.getLogger(__name__)

_TASK_NAME = "run_sandbox"

# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------

class RunSandboxInput(BaseModel):
    """Input for the run_sandbox task.

    Attributes:
        script:   Source code to execute.  Must be a self-contained script;
                  all required data should arrive via *stdin* or be written
                  inline.
        language: Interpreter: ``"python"`` (default) or ``"bash"``.
        stdin:    Text piped to the process stdin (default: empty string).
    """

    script: str = Field(description="Source code (Python or bash) to execute inside the sandbox.")
    language: str = Field(
        default="python",
        description="Interpreter: 'python' or 'bash'.",
    )
    stdin: str = Field(
        default="",
        description="Text piped to the process stdin.",
    )

class RunSandboxOutput(BaseModel):
    """Output from the run_sandbox task.

    Attributes:
        stdout:    Captured stdout from the script (the primary result).
        stderr:    Captured stderr (populated on errors or explicit writes).
        exit_code: Process exit code; 0 = success.
        timed_out: True when the script was killed by the wall-clock timeout.
    """

    stdout: str = Field(description="Captured stdout from the sandboxed script.")
    stderr: str = Field(default="", description="Captured stderr from the sandboxed script.")
    exit_code: int = Field(description="Process exit code; 0 = success.")
    timed_out: bool = Field(default=False, description="True if killed by timeout.")

# ---------------------------------------------------------------------------
# Celery layer -- business logic
# ---------------------------------------------------------------------------

async def _handler(payload: dict) -> dict:
    """Validate and execute a sandboxed script.

    Called by ``completion_task.run_completion`` inside a Celery worker.
    Runs the full sandbox isolation stack: security validation -> isolated
    temp dir -> subprocess with network-ns + resource limits + timeout.

    Args:
        payload: Serialised :class:`RunSandboxInput` dict.

    Returns:
        Serialised :class:`RunSandboxOutput` dict.

    Raises:
        SandboxSecurityError: Script contained a blocked pattern.
        SandboxTimeoutError:  Execution exceeded the wall-clock limit.
        SandboxSpawnError:    OS could not exec the interpreter binary.
        SandboxUnsupportedLanguageError: Language is not ``python`` or ``bash``.
    """
    from backend.config import get_settings  # noqa: PLC0415 -- deferred for Celery worker import order
    from backend.sandbox.environment import sandbox_workdir  # noqa: PLC0415
    from backend.sandbox.executor import execute_bash, execute_python  # noqa: PLC0415
    from backend.sandbox.errors import SandboxUnsupportedLanguageError  # noqa: PLC0415
    from backend.sandbox.errors.codes import SANDBOX_UNSUPPORTED_LANGUAGE  # noqa: PLC0415
    from backend.sandbox.security import validate_script  # noqa: PLC0415

    inp = RunSandboxInput.model_validate(payload)

    if inp.language not in ("python", "bash"):
        raise SandboxUnsupportedLanguageError(
            f"[{SANDBOX_UNSUPPORTED_LANGUAGE}] Unsupported language: {inp.language!r}. "
            "Use 'python' or 'bash'."
        )

    validate_script(inp.script, language=inp.language)

    settings = get_settings()
    async with sandbox_workdir(settings.SANDBOX_DIR) as work_dir:
        if inp.language == "python":
            result = await execute_python(inp.script, stdin=inp.stdin, work_dir=work_dir)
        else:
            result = await execute_bash(inp.script, stdin=inp.stdin, work_dir=work_dir)

    return RunSandboxOutput(
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
        timed_out=result.timed_out,
    ).model_dump()

# ---------------------------------------------------------------------------
# LangGraph layer -- @task orchestration
# ---------------------------------------------------------------------------

async def _run_sandbox_task(
    task_input: TaskInput[RunSandboxInput],
) -> TaskOutput[RunSandboxOutput]:
    """LangGraph @task: delegate run_sandbox to the Celery completion worker.

    Args:
        task_input: Typed envelope with :class:`~backend.langgraph.models.models.TaskContext`
                    and :class:`RunSandboxInput` content.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`RunSandboxOutput`.

    Raises:
        SandboxSecurityError: Script was rejected by pre-execution validation.
        SandboxTimeoutError:  Execution hit the wall-clock limit.
        SandboxSpawnError:    Interpreter binary not found or OS exec failed.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump()

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type="Json",
    )
    try:
        result = await delegate_completion(
            ctx.thread_id, ctx.task_id, ctx.node_id, ctx.node_name, ctx.task_name, payload,
        )
    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            failed=True, error=str(exc),
        )
        raise

    output = RunSandboxOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)

# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

run_sandbox = NodeTask(
    name=_TASK_NAME,
    description=(
        "Execute a self-contained Python or bash script inside an isolated sandbox. "
        "The sandbox has no network access and is confined to a temporary directory "
        "that is deleted on completion. Accepts the script source code, optional stdin "
        "text, and returns stdout, stderr, and the exit code. "
        "Typical use: LLM-generated data-processing scripts (e.g. convert scraped "
        "markdown/CSV text to JSON for downstream stats ingestion)."
    ),
    input_type=RunSandboxInput,
    output_type=RunSandboxOutput,
    task_fn=_run_sandbox_task,
    handler=_handler,
)

HANDLERS: dict = {_TASK_NAME: _handler}

__all__ = ["run_sandbox", "RunSandboxInput", "RunSandboxOutput", "HANDLERS"]
