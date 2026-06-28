"""Docker Engine health check and Docker Desktop startup from WSL.

Python runs inside WSL (Linux) while Docker Desktop runs as a Windows
application.  The Docker CLI inside WSL communicates with the engine via the
WSL-integration socket exposed by Docker Desktop, so:

* ``docker info`` succeeds iff Docker Desktop is running and WSL integration
  has been enabled for the current distro.
* To start Docker Desktop we invoke the Windows ``.exe`` through WSL's
  ``/mnt/c/...`` path (or fall back to ``powershell.exe Start-Process``).
"""
import os
import shutil
import subprocess
import sys
import time


def _is_wsl() -> bool:
    """Return ``True`` when the current interpreter runs under WSL."""
    try:
        with open("/proc/version", "r") as fh:
            return "microsoft" in fh.read().lower()
    except (OSError, IOError):
        return False


def _docker_info_works(timeout: float = 5.0) -> bool:
    """Return ``True`` when ``docker info`` completes successfully."""
    docker_exe = shutil.which("docker")
    if not docker_exe:
        return False
    try:
        completed = subprocess.run(
            [docker_exe, "info"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _find_docker_desktop_exe() -> str | None:
    """Locate the Docker Desktop Windows executable from inside WSL.

    Returns a WSL-style path (``/mnt/c/.../Docker Desktop.exe``) or ``None``
    when the file does not exist at the usual install locations.
    """
    candidates = [
        "/mnt/c/Program Files/Docker/Docker/Docker Desktop.exe",
        "/mnt/c/Program Files (x86)/Docker/Docker/Docker Desktop.exe",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _launch_docker_desktop_wsl() -> bool:
    """Start Docker Desktop from inside WSL.

    Strategy order:
        1. Call ``Docker Desktop.exe`` directly (preferred because explicit).
        2. Fall back to ``powershell.exe Start-Process "Docker Desktop"``.

    Returns ``True`` when a launch command was dispatched (does *not* wait for
    the engine to be ready — callers should poll :func:`_docker_info_works`).
    """
    desktop_exe = _find_docker_desktop_exe()
    if desktop_exe:
        print("[run.py] Starting Docker Desktop via:", desktop_exe)
        try:
            subprocess.Popen(
                [desktop_exe],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError as exc:
            print(f"[run.py] Direct Docker Desktop launch failed: {exc}")

    powershell = shutil.which("powershell.exe")
    if powershell:
        print("[run.py] Starting Docker Desktop via powershell.exe Start-Process")
        try:
            subprocess.Popen(
                [powershell, "-NoProfile", "-Command",
                 'Start-Process -FilePath "${Env:ProgramFiles}\\Docker\\Docker\\Docker Desktop.exe"'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError as exc:
            print(f"[run.py] powershell.exe launch failed: {exc}")

    cmd_exe = shutil.which("cmd.exe")
    if cmd_exe:
        print("[run.py] Starting Docker Desktop via cmd.exe start")
        try:
            subprocess.Popen(
                [cmd_exe, "/C", "start", "",
                 r"C:\Program Files\Docker\Docker\Docker Desktop.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError as exc:
            print(f"[run.py] cmd.exe launch failed: {exc}")

    return False


def ensure_docker_running(
    check_timeout: float = 5.0,
    start_timeout: float = 120.0,
    poll_interval: float = 5.0,
) -> bool:
    """Ensure the Docker Engine is reachable, starting Docker Desktop if needed.

    Args:
        check_timeout:   Seconds to wait for a single ``docker info`` call.
        start_timeout:   Maximum seconds to wait for Docker Desktop to become
                         ready after launch is triggered.
        poll_interval:   Seconds between readiness polls while waiting.

    Returns:
        ``True`` when the engine is reachable on return, ``False`` otherwise
        (including when Docker CLI is not installed or no launch mechanism
        could be invoked).
    """
    if not shutil.which("docker"):
        print("[run.py] WARNING: 'docker' CLI not found on PATH — skipping Docker check")
        return False

    if _docker_info_works(timeout=check_timeout):
        return True

    running_in_wsl = _is_wsl()
    is_windows = sys.platform == "win32"

    if running_in_wsl:
        print("[run.py] Docker Engine not reachable; running inside WSL.")
        launched = _launch_docker_desktop_wsl()
    elif is_windows:
        print("[run.py] Docker Engine not reachable; running on native Windows.")
        launched = _launch_docker_desktop_windows()
    else:
        print("[run.py] Docker Engine not reachable on Linux (no Docker Desktop GUI).")
        launched = _start_docker_service_linux()

    if not launched:
        print("[run.py] WARNING: could not trigger Docker start — continuing anyway")
        return False

    deadline = time.time() + start_timeout
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        time.sleep(poll_interval)
        if _docker_info_works(timeout=check_timeout):
            print(
                f"[run.py] Docker Engine is ready"
                f" (waited ~{attempt * poll_interval:.0f}s)"
            )
            return True
        print(
            f"[run.py] Waiting for Docker Engine ..."
            f" ({attempt * poll_interval:.0f}s / {start_timeout:.0f}s)"
        )

    print(
        f"[run.py] WARNING: Docker Engine still not ready after {start_timeout:.0f}s"
    )
    return False


def _launch_docker_desktop_windows() -> bool:
    """Start Docker Desktop on native Windows (no WSL)."""
    candidates = [
        r"C:\Program Files\Docker\Docker\Docker Desktop.exe",
        r"C:\Program Files (x86)\Docker\Docker\Docker Desktop.exe",
    ]
    for path in candidates:
        if os.path.isfile(path):
            print("[run.py] Starting Docker Desktop via:", path)
            try:
                subprocess.Popen(
                    [path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
            except OSError as exc:
                print(f"[run.py] Direct launch failed: {exc}")
    return False


def _start_docker_service_linux() -> bool:
    """Start the Docker service on bare-metal Linux (no WSL / no Docker Desktop)."""
    for init_cmd in (
        ["systemctl", "start", "docker"],
        ["service", "docker", "start"],
        ["sudo", "systemctl", "start", "docker"],
        ["sudo", "service", "docker", "start"],
    ):
        exe = shutil.which(init_cmd[0])
        if not exe:
            continue
        print("[run.py] Starting Docker service via:", " ".join(init_cmd))
        try:
            completed = subprocess.run(
                [exe, *init_cmd[1:]],
                capture_output=True,
                text=True,
                timeout=30.0,
            )
            if completed.returncode == 0:
                return True
            print(f"[run.py] {init_cmd[0]} exited {completed.returncode}: {completed.stderr.strip()}")
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"[run.py] {init_cmd[0]} error: {exc}")
    return False
