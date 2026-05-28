"""Subprocess executor for the sandbox runner container.

Isolation layers
----------------
* **Network** — handled entirely by Docker (``internal: true`` network);
  no ``unshare --net`` needed inside the container.
* **Filesystem** — CWD is pinned to ``/sandbox/{node_id}/``; the security
  validator blocks ``../`` escapes before this function is reached.
* **Resources** — ``setrlimit`` caps virtual memory, CPU time, child-process
  count, and open-file descriptors.  Values are read from environment
  variables so they can be tuned per container without rebuilding.
* **Timeout** — wall-clock cap via ``proc.communicate(timeout=N)``;
  the process is killed on expiry.
* **Output cap** — stdout and stderr are each truncated at
  ``SANDBOX_MAX_OUTPUT_BYTES`` characters.

All settings are read from environment variables at module load time so they
apply uniformly to every execution within the container process.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable
from uuid import uuid4

# ── Settings from env ──────────────────────────────────────────────────────────

TIMEOUT_SECONDS: int = int(os.getenv("SANDBOX_TIMEOUT_SECONDS", "60"))
MAX_MEMORY_MB: int = int(os.getenv("SANDBOX_MAX_MEMORY_MB", "256"))
MAX_CPU_SECONDS: int = int(os.getenv("SANDBOX_MAX_CPU_SECONDS", "30"))
MAX_PROCS: int = int(os.getenv("SANDBOX_MAX_PROCS", "64"))
MAX_OPEN_FILES: int = int(os.getenv("SANDBOX_MAX_OPEN_FILES", "64"))
MAX_OUTPUT: int = int(os.getenv("SANDBOX_MAX_OUTPUT_BYTES", "1048576"))
# Read-only DSN for fin_markets queries (sandbox-read role, replica only).
# Passed through to child processes as PG_SANDBOX_DSN.
_PG_SANDBOX_DSN: str = os.getenv("SANDBOX_PG_DSN", "")


# ── Resource limits ────────────────────────────────────────────────────────────


def _make_limit_fn(
    max_mem_mb: int,
    max_cpu_s: int,
    max_procs: int,
    max_files: int,
) -> Callable[[], None]:
    """Return a ``preexec_fn`` that applies resource limits inside the child."""
    mem_bytes = max_mem_mb * 1024 * 1024

    def _apply() -> None:
        try:
            import resource as _r  # noqa: PLC0415

            def _clamp(rid: int, desired: int) -> None:
                try:
                    _, hard = _r.getrlimit(rid)
                    limit = desired if hard == _r.RLIM_INFINITY else min(desired, hard)
                    _r.setrlimit(rid, (limit, limit))
                except (ValueError, OSError):
                    pass

            _clamp(_r.RLIMIT_AS, mem_bytes)
            _clamp(_r.RLIMIT_CPU, max_cpu_s)
            if hasattr(_r, "RLIMIT_NPROC"):
                _clamp(_r.RLIMIT_NPROC, max_procs)
            _clamp(_r.RLIMIT_NOFILE, max_files)
        except Exception:  # noqa: BLE001
            pass

    return _apply


# ── Environment ────────────────────────────────────────────────────────────────


def _sandbox_env(work_dir: Path) -> dict[str, str]:
    """Return a stripped, safe environment for the child process."""
    env: dict[str, str] = {
        "HOME": str(work_dir),
        "TMPDIR": str(work_dir),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": "",
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
    }
    if _PG_SANDBOX_DSN:
        env["PG_SANDBOX_DSN"] = _PG_SANDBOX_DSN
    return env


# ── Blocking subprocess ────────────────────────────────────────────────────────


def _run_blocking(
    cmd: list[str],
    stdin: str,
    work_dir: Path,
) -> dict:
    """Spawn the subprocess and return a result dict."""
    preexec = _make_limit_fn(MAX_MEMORY_MB, MAX_CPU_SECONDS, MAX_PROCS, MAX_OPEN_FILES)

    try:
        with subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(work_dir),
            env=_sandbox_env(work_dir),
            preexec_fn=preexec,
        ) as proc:
            try:
                out_b, err_b = proc.communicate(
                    input=stdin.encode("utf-8"),
                    timeout=TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired:
                proc.kill()
                out_b, err_b = proc.communicate()
                return {
                    "stdout": "",
                    "stderr": f"Execution killed after {TIMEOUT_SECONDS}s wall-clock timeout.",
                    "exit_code": -1,
                    "timed_out": True,
                }
    except FileNotFoundError as exc:
        return {"stdout": "", "stderr": f"Binary not found: {exc}", "exit_code": -1, "timed_out": False}
    except OSError as exc:
        return {"stdout": "", "stderr": f"Spawn failed: {exc}", "exit_code": -1, "timed_out": False}

    stdout = out_b.decode("utf-8", errors="replace")
    stderr = err_b.decode("utf-8", errors="replace")

    if len(stdout) > MAX_OUTPUT:
        stdout = stdout[:MAX_OUTPUT]
        stderr = (stderr + f"\n[stdout truncated at {MAX_OUTPUT} characters]").strip()
    if len(stderr) > MAX_OUTPUT:
        stderr = stderr[:MAX_OUTPUT] + f"\n[stderr truncated at {MAX_OUTPUT} characters]"

    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": proc.returncode,
        "timed_out": False,
    }


# ── Public API ─────────────────────────────────────────────────────────────────


async def execute_python(script: str, *, stdin: str = "", work_dir: Path) -> dict:
    """Execute a Python script inside the sandbox workdir.

    The script is written to a uniquely-named file so concurrent calls for
    the same node do not race on the script file while still sharing the
    persistent working directory for data files.

    Args:
        script:   Python source code.
        stdin:    Text piped to stdin.
        work_dir: Node sandbox directory (``/sandbox/{node_id}/``).

    Returns:
        ``{stdout, stderr, exit_code, timed_out}`` dict.
    """
    script_path = work_dir / f"script_{uuid4().hex}.py"
    script_path.write_text(script, encoding="utf-8")
    return await asyncio.to_thread(
        _run_blocking,
        [sys.executable, str(script_path)],
        stdin,
        work_dir,
    )


async def execute_bash(script: str, *, stdin: str = "", work_dir: Path) -> dict:
    """Execute a bash script inside the sandbox workdir.

    Args:
        script:   Bash source code.
        stdin:    Text piped to stdin.
        work_dir: Node sandbox directory (``/sandbox/{node_id}/``).

    Returns:
        ``{stdout, stderr, exit_code, timed_out}`` dict.
    """
    import shutil  # noqa: PLC0415

    script_path = work_dir / f"script_{uuid4().hex}.sh"
    script_path.write_text(script, encoding="utf-8")
    script_path.chmod(0o700)
    bash_exe = shutil.which("bash") or "/bin/bash"
    return await asyncio.to_thread(
        _run_blocking,
        [bash_exe, str(script_path)],
        stdin,
        work_dir,
    )
