"""Error codes for the sandbox module."""

from __future__ import annotations

# SB001 -- wall-clock timeout exceeded
SANDBOX_TIMEOUT = "SB001"

# SB002 -- pre-execution security validation rejected the script
SANDBOX_SECURITY_VIOLATION = "SB002"

# SB003 -- OS-level failure spawning the subprocess (e.g. binary not found)
SANDBOX_SPAWN_ERROR = "SB003"

# SB004 -- combined stdout+stderr exceeded the configured byte cap
SANDBOX_OUTPUT_LIMIT_EXCEEDED = "SB004"

# SB005 -- failed to create or clean up the sandbox working directory
SANDBOX_ENV_ERROR = "SB005"

# SB006 -- unsupported language requested
SANDBOX_UNSUPPORTED_LANGUAGE = "SB006"

# SB007 -- cannot reach the sandbox runner container (connectivity or config error)
SANDBOX_RUNNER_ERROR = "SB007"

# SB008 -- stdout is empty but stderr contains data (script produced no output, likely failed)
SANDBOX_NO_STDOUT = "SB008"

SANDBOX_ERROR_DESCRIPTIONS: dict[str, str] = {
    SANDBOX_TIMEOUT: "Sandbox execution exceeded the wall-clock time limit.",
    SANDBOX_SECURITY_VIOLATION: "Script was rejected by pre-execution security validation.",
    SANDBOX_SPAWN_ERROR: "OS failed to spawn the sandbox subprocess.",
    SANDBOX_OUTPUT_LIMIT_EXCEEDED: "Sandbox output exceeded the configured byte cap.",
    SANDBOX_ENV_ERROR: "Failed to create or clean up the sandbox working directory.",
    SANDBOX_UNSUPPORTED_LANGUAGE: "Requested execution language is not supported.",
    SANDBOX_RUNNER_ERROR: "Cannot reach the sandbox runner container.",
    SANDBOX_NO_STDOUT: "Script produced no stdout but wrote to stderr.",
}
