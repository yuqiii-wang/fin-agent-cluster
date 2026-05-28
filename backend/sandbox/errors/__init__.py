"""Sandbox exception hierarchy."""

from __future__ import annotations

from backend.sandbox.errors.codes import (
    SANDBOX_TIMEOUT,
    SANDBOX_SECURITY_VIOLATION,
    SANDBOX_SPAWN_ERROR,
    SANDBOX_OUTPUT_LIMIT_EXCEEDED,
    SANDBOX_ENV_ERROR,
    SANDBOX_UNSUPPORTED_LANGUAGE,
    SANDBOX_RUNNER_ERROR,
)

__all__ = [
    "SandboxTimeoutError",
    "SandboxSecurityError",
    "SandboxSpawnError",
    "SandboxOutputLimitError",
    "SandboxEnvError",
    "SandboxUnsupportedLanguageError",
    "SandboxRunnerError",
]


class SandboxTimeoutError(Exception):
    """Raised when sandbox execution exceeds the wall-clock timeout (SB001)."""

    code = SANDBOX_TIMEOUT


class SandboxSecurityError(Exception):
    """Raised when a script contains a blocked pattern (SB002)."""

    code = SANDBOX_SECURITY_VIOLATION


class SandboxSpawnError(Exception):
    """Raised on OS-level failure to spawn the subprocess (SB003)."""

    code = SANDBOX_SPAWN_ERROR


class SandboxOutputLimitError(Exception):
    """Raised when combined output exceeds the configured byte cap (SB004)."""

    code = SANDBOX_OUTPUT_LIMIT_EXCEEDED


class SandboxEnvError(Exception):
    """Raised when the sandbox temp directory cannot be created (SB005)."""

    code = SANDBOX_ENV_ERROR


class SandboxUnsupportedLanguageError(Exception):
    """Raised when an unsupported execution language is requested (SB006)."""

    code = SANDBOX_UNSUPPORTED_LANGUAGE


class SandboxRunnerError(Exception):
    """Raised when the sandbox runner container is unreachable or returns an unexpected error (SB007)."""

    code = SANDBOX_RUNNER_ERROR
