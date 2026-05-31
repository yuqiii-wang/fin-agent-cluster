"""run_sandbox — NodeTask: execute LLM-generated Python or bash inside an isolated sandbox.

Execution runs inside Docker ``sandbox-runner-N`` containers.  Thread-ID
sharding routes every call for the same LangGraph thread to the same
container so files written by earlier tasks are visible to later tasks.

Execution layers
----------------
LangGraph layer (``_run_sandbox_task`` decorated with ``@task``):
    Creates the DB task row, injects ``_node_id`` and ``_thread_id`` into
    the payload, delegates to the Celery completion worker, and returns a
    :class:`~backend.langgraph.models.models.TaskOutput`.

Celery layer (``_handler``):
    1. Pre-flight security validation with
       :func:`~backend.sandbox.security.validate_script` (early rejection
       before the HTTP call).
    2. POSTs the script to the runner container via
       :func:`~backend.sandbox.client.execute_in_runner`.
    3. Returns serialised :class:`RunSandboxOutput`.

Public exports
--------------
``run_sandbox``      — :class:`~backend.langgraph.models.task.NodeTask` instance.
``RunSandboxInput``  — Pydantic input model.
``RunSandboxOutput`` — Pydantic output model.
``HANDLERS``         — dict slice for registration in
                       ``backend.langgraph.nodes.HANDLERS``.
"""

from __future__ import annotations

import logging

from langgraph.func import task
from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.models import BaseTaskInput, TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask

logger = logging.getLogger(__name__)

_TASK_NAME = "run_sandbox"


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class RunSandboxInput(BaseTaskInput):
    """Input for the run_sandbox task.

    Attributes:
        script:           Source code to execute.  Must be a self-contained script;
                          all required data should arrive via *stdin* or be written
                          inline.
        language:         Interpreter: ``"python"`` (default) or ``"bash"``.
        stdin:            Text piped to the process stdin (default: empty string).
        from_maybe_cache: Inherited from :class:`~backend.langgraph.models.models.BaseTaskInput`.
                          When ``False`` the task-runner skips all DB/PG cache reads
                          and forces a fresh execution.
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
# Celery layer — business logic
# ---------------------------------------------------------------------------


async def _handler(payload: dict) -> dict:
    """Validate and execute a sandboxed script via the runner container.

    Called by ``completion_task.run_completion`` inside a Celery worker.
    Performs a pre-flight security check then delegates execution to the
    correct ``sandbox-runner-N`` shard via HTTP.

    Args:
        payload: Serialised :class:`RunSandboxInput` dict enriched with
                 ``_node_id`` and ``_thread_id`` injected by
                 :func:`_run_sandbox_task`.

    Returns:
        Serialised :class:`RunSandboxOutput` dict.

    Raises:
        SandboxSecurityError:            Script contained a blocked pattern.
        SandboxUnsupportedLanguageError: Language is not ``python`` or ``bash``.
        SandboxTimeoutError:             Execution exceeded the wall-clock limit.
        SandboxRunnerError:              Runner container unreachable.
    """
    from backend.config import get_settings  # noqa: PLC0415 — deferred for Celery worker import order
    from backend.sandbox.client import execute_in_runner  # noqa: PLC0415
    from backend.sandbox.errors import SandboxUnsupportedLanguageError, SandboxNoStdoutError  # noqa: PLC0415
    from backend.sandbox.errors.codes import SANDBOX_UNSUPPORTED_LANGUAGE, SANDBOX_NO_STDOUT  # noqa: PLC0415
    from backend.sandbox.security import validate_script  # noqa: PLC0415

    node_id: str = payload.pop("_node_id", "")
    thread_id: str = payload.pop("_thread_id", "")

    inp = RunSandboxInput.model_validate(payload)

    if inp.language not in ("python", "bash"):
        raise SandboxUnsupportedLanguageError(
            f"[{SANDBOX_UNSUPPORTED_LANGUAGE}] Unsupported language: {inp.language!r}. "
            "Use 'python' or 'bash'."
        )

    # Pre-flight check — reject obvious violations before the HTTP round-trip.
    validate_script(inp.script, language=inp.language)

    settings = get_settings()
    result_dict = await execute_in_runner(
        thread_id=thread_id,
        node_id=node_id,
        script=inp.script,
        language=inp.language,
        stdin=inp.stdin,
        nodes=settings.SANDBOX_RUNNER_NODES,
        timeout=settings.SANDBOX_RUNNER_TIMEOUT_SECONDS,
    )

    if not result_dict.get("stdout") and result_dict.get("stderr"):
        raise SandboxNoStdoutError(
            f"[{SANDBOX_NO_STDOUT}] Script produced no stdout but stderr contains: "
            f"{result_dict['stderr'][:500]}"
        )

    return RunSandboxOutput.model_validate(result_dict).model_dump()


# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------


@task
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
        SandboxSecurityError:            Script was rejected by pre-execution validation.
        SandboxUnsupportedLanguageError: Language is not supported.
        SandboxTimeoutError:             Execution hit the wall-clock limit.
        SandboxRunnerError:              Runner container unreachable.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump()
    # Inject routing keys so the Celery handler can target the correct shard and workdir.
    payload["_node_id"] = ctx.node_id
    payload["_thread_id"] = ctx.thread_id

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
        "The sandbox has no network access and is confined to a persistent working "
        "directory shared across all tasks in the same agent node execution. "
        "Files written by earlier tasks can be read by later tasks. "
        "Returns stdout, stderr, and the exit code. "
        "Typical use: LLM-generated data-processing scripts (e.g. convert scraped "
        "markdown/CSV text to JSON for downstream stats ingestion)."
    ),
    input_type=RunSandboxInput,
    output_type=RunSandboxOutput,
    task_fn=_run_sandbox_task,
    handler=_handler,
)


HANDLERS: dict = {_TASK_NAME: _handler}

__all__ = [
    "run_sandbox",
    "RunSandboxInput",
    "RunSandboxOutput",
    "HANDLERS",
]
