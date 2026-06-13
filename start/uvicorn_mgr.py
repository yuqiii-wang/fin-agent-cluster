"""Start / stop uvicorn subprocesses."""
import os
import signal
import subprocess
import sys


def start_uvicorn_instances(
    base_port: int,
    count: int,
    app_module: str,
    log_config_path: str,
    extra_env_per_instance: list[dict] | None = None,
) -> list[subprocess.Popen]:
    """Start *count* uvicorn instances on consecutive ports starting at *base_port*.

    Args:
        base_port: First port to bind; subsequent instances increment by 1.
        count: Number of instances to start.
        app_module: Python module path for the ASGI app, e.g. ``"backend.main:app"``.
        log_config_path: Path to the JSON logging config file for ``--log-config``.
        extra_env_per_instance: Optional list of per-instance env-var overrides
            (index-aligned).  If shorter than *count*, remaining instances use
            no overrides.

    Returns:
        List of :class:`subprocess.Popen` handles.
    """
    procs: list[subprocess.Popen] = []
    _creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    for i in range(count):
        port = base_port + i
        instance_env = os.environ.copy()
        if extra_env_per_instance and i < len(extra_env_per_instance):
            instance_env.update(extra_env_per_instance[i])
        instance_env["FASTAPI_PORT"] = str(port)
        cmd = [
            sys.executable, "-m", "uvicorn",
            app_module,
            "--host", "127.0.0.1",
            "--port", str(port),
            "--reload",
            "--reload-dir", "backend",
            "--log-config", log_config_path,
        ]
        print(f"[run.py] Starting {app_module} instance {i + 1}/{count} on port {port} ...")
        procs.append(subprocess.Popen(cmd, env=instance_env, creationflags=_creation_flags))
    return procs


def stop_uvicorn_instances(procs: list[subprocess.Popen]) -> None:
    """Terminate all uvicorn instances gracefully, then forcefully."""
    for proc in procs:
        if proc.poll() is None:
            if sys.platform == "win32":
                try:
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                except (OSError, PermissionError):
                    proc.terminate()
            else:
                proc.terminate()
    for proc in procs:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
