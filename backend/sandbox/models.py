"""Sandbox I/O pydantic models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

__all__ = ["SandboxInput", "SandboxResult", "SandboxLanguage"]

SandboxLanguage = Literal["python", "bash"]


class SandboxInput(BaseModel):
    """Input to a sandbox execution request.

    Attributes:
        script:   Source code (Python or bash) to execute inside the sandbox.
        language: Interpreter to use; either ``"python"`` or ``"bash"``.
        stdin:    Text piped to the process stdin (default: empty string).
    """

    script: str = Field(description="Source code to execute inside the sandbox.")
    language: SandboxLanguage = Field(
        default="python",
        description="Interpreter: 'python' or 'bash'.",
    )
    stdin: str = Field(
        default="",
        description="Text piped to the process stdin.",
    )


class SandboxResult(BaseModel):
    """Output from a sandbox execution.

    Attributes:
        stdout:    Captured stdout, capped at ``SANDBOX_MAX_OUTPUT_BYTES``.
        stderr:    Captured stderr, capped at ``SANDBOX_MAX_OUTPUT_BYTES``.
        exit_code: Process exit code; 0 indicates success.
        timed_out: True when execution was killed by the wall-clock timeout.
    """

    stdout: str = Field(description="Captured stdout.")
    stderr: str = Field(default="", description="Captured stderr.")
    exit_code: int = Field(description="Process exit code; 0 = success.")
    timed_out: bool = Field(
        default=False,
        description="True when execution was killed by the wall-clock timeout.",
    )
