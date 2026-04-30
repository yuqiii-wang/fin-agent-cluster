"""Run the FastAPI server with proper Windows asyncio configuration."""
import asyncio
import atexit
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from backend.config import get_settings
from backend.log_config import configure_logging, get_logging_config


_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def _configure_proxy(proxy: str | None) -> None:
    """Inject outbound proxy into os.environ so every HTTP library picks it up.

    Covers: httpx (trust_env=True default), requests (yfinance/DDGS), openai SDK,
    google-generativeai, and any other env-aware HTTP client.
    Sets NO_PROXY to exclude localhost so DB and local health checks are unaffected.

    Args:
        proxy: Proxy URL (e.g. ``'http://127.0.0.1:7890'``) or ``None`` to skip.
    """
    if proxy:
        import socket
        from urllib.parse import urlparse
        
        reachable = False
        try:
            parsed = urlparse(proxy)
            host, port = parsed.hostname, parsed.port
            if host and port:
                with socket.create_connection((host, port), timeout=1.0):
                    reachable = True
        except (OSError, ValueError):
            pass

        if reachable:
            print(f"Proxy {proxy} is reachable. Configuring environment variables.")
            for var in _PROXY_ENV_KEYS:
                os.environ[var] = proxy
        else:
            print(f"Proxy {proxy} is not reachable. Clearing proxy environment variables.")
            for var in _PROXY_ENV_KEYS:
                os.environ.pop(var, None)
    else:
        # Explicit no-proxy mode: remove inherited shell/editor proxy vars.
        for var in _PROXY_ENV_KEYS:
            os.environ.pop(var, None)
            
    # Always exclude local addresses regardless of proxy setting
    no_proxy = "localhost,127.0.0.1,::1"
    os.environ["NO_PROXY"] = no_proxy
    os.environ["no_proxy"] = no_proxy


def _start_celery(concurrency: int = 2) -> list[subprocess.Popen]:
    """Start a single ``celery-ingest`` worker.

    The worker consumes from the ``stream:ingest`` queue.  Beat scheduling is
    not used — all tasks are dispatched on demand (no beat_schedule is defined).

    Returns:
        List of :class:`subprocess.Popen` handles to pass to :func:`_stop_celery`.
    """
    is_windows = sys.platform == "win32"
    pool = "gevent" if is_windows else "prefork"
    env = os.environ.copy()
    _creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if is_windows else 0

    cmd = [
        sys.executable, "-m", "celery",
        "-A", "backend.streaming.celery_app.celery_app",
        "worker",
        "-Q", "stream:ingest",
        "-n", f"celery-ingest-{os.getpid()}@%h",
        f"--concurrency={concurrency}",
        f"--pool={pool}",
        "--loglevel=info",
    ]
    if not is_windows:
        cmd += ["--without-gossip", "--without-mingle"]

    print(f"[run.py] Starting celery-ingest (concurrency={concurrency}, pool={pool}) ...")
    return [subprocess.Popen(cmd, env=env, creationflags=_creation_flags)]




def _stop_celery(procs: list[subprocess.Popen]) -> None:
    """Terminate all Celery subprocesses gracefully, then forcefully."""
    for proc in procs:
        if proc.poll() is None:
            if sys.platform == "win32":
                import signal as _signal
                try:
                    proc.send_signal(_signal.CTRL_BREAK_EVENT)
                except (OSError, PermissionError):
                    proc.terminate()
            else:
                proc.terminate()
    for proc in procs:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _create_job_object() -> "int | None":
    """Create a Windows Job Object with KILL_ON_JOB_CLOSE (no-op on Unix)."""
    if sys.platform != "win32":
        return None
    import ctypes
    import ctypes.wintypes

    kernel32 = ctypes.windll.kernel32
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None

    # JOBOBJECT_EXTENDED_LIMIT_INFORMATION with KILL_ON_JOB_CLOSE
    class _BASIC(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class _IO(ctypes.Structure):
        _fields_ = [(f, ctypes.c_uint64) for f in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]

    class _EXT(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BASIC),
            ("IoInfo", _IO),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JobObjectExtendedLimitInformation = 9

    info = _EXT()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = kernel32.SetInformationJobObject(
        job,
        JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        kernel32.CloseHandle(job)
        return None
    return job


def _assign_to_job(job: "int | None", proc: subprocess.Popen) -> None:
    """Assign *proc* to the Windows Job Object *job* (no-op if *job* is None)."""
    if sys.platform != "win32" or not job:
        return
    import ctypes
    PROCESS_ALL_ACCESS = 0x1F0FFF
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, proc.pid)
    if handle:
        kernel32.AssignProcessToJobObject(job, handle)
        kernel32.CloseHandle(handle)


def _write_log_config(log_config: dict) -> str:
    """Write *log_config* dict to a temp JSON file for uvicorn CLI ``--log-config``.

    Returns:
        Absolute path to the written temp file.
    """
    fd, path = tempfile.mkstemp(suffix=".json", prefix="uvicorn_log_")
    with os.fdopen(fd, "w") as f:
        json.dump(log_config, f)
    return path


def _start_uvicorn_instances(
    base_port: int,
    count: int,
    app_module: str,
    log_config_path: str,
) -> list[subprocess.Popen]:
    """Start *count* uvicorn instances on consecutive ports starting at *base_port*.

    Args:
        base_port: First port to bind; subsequent instances increment by 1.
        count: Number of instances to start.
        app_module: Python module path for the ASGI app, e.g. ``"backend.main:app"``.
        log_config_path: Path to the JSON logging config file for ``--log-config``.

    Returns:
        List of :class:`subprocess.Popen` handles.
    """
    procs: list[subprocess.Popen] = []
    _creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    for i in range(count):
        port = base_port + i
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
        procs.append(subprocess.Popen(cmd, env=os.environ.copy(), creationflags=_creation_flags))
    return procs


def _stop_uvicorn_instances(procs: list[subprocess.Popen]) -> None:
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


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run the FastAPI server.")
    parser.add_argument("--no-proxy", action="store_true", help="Disable the use of the proxy even if configured.")
    parser.add_argument("--no-celery", action="store_true", help="Skip starting Celery workers (FastAPI fallback threads will be used instead).")
    parser.add_argument("--celery-concurrency", type=int, default=8, metavar="N", help="Number of Celery worker threads (default: 8).")
    parser.add_argument("--runner-instances", type=int, default=4, metavar="N", help="Number of runner FastAPI instances (default: 4, ports FASTAPI_PORT..FASTAPI_PORT+N-1).")
    parser.add_argument("--assistant-instances", type=int, default=2, metavar="N", help="Number of assistant FastAPI instances (default: 2, ports FASTAPI_ASSISTANT_PORT..+N-1).")
    args = parser.parse_args()

    settings = get_settings()
    proxy_to_use = None if args.no_proxy else settings.HTTP_PROXY
    _configure_proxy(proxy_to_use)

    if sys.platform == "win32":
        # psycopg requires SelectorEventLoop on Windows.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    configure_logging()

    _job = _create_job_object()  # kills children automatically on parent exit

    celery_procs: list[subprocess.Popen] = []
    if not args.no_celery:
        celery_procs = _start_celery(concurrency=args.celery_concurrency)
        for _p in celery_procs:
            _assign_to_job(_job, _p)
        atexit.register(_stop_celery, celery_procs)

    log_config_path = _write_log_config(get_logging_config())
    atexit.register(lambda: os.unlink(log_config_path) if os.path.exists(log_config_path) else None)

    # Start runner instances (full LangGraph + Celery capability).
    runner_procs = _start_uvicorn_instances(
        base_port=settings.FASTAPI_PORT,
        count=args.runner_instances,
        app_module="backend.main:app",
        log_config_path=log_config_path,
    )
    for _p in runner_procs:
        _assign_to_job(_job, _p)
    atexit.register(_stop_uvicorn_instances, runner_procs)

    # Start assistant instances (non-LangGraph, query-read / data-serve only).
    assistant_procs = _start_uvicorn_instances(
        base_port=settings.FASTAPI_ASSISTANT_PORT,
        count=args.assistant_instances,
        app_module="backend.assistant.main:app",
        log_config_path=log_config_path,
    )
    for _p in assistant_procs:
        _assign_to_job(_job, _p)
    atexit.register(_stop_uvicorn_instances, assistant_procs)

    all_procs = runner_procs + assistant_procs

    def _shutdown(signum, frame) -> None:  # type: ignore[misc]
        """Forward SIGTERM/SIGINT to a clean sys.exit so atexit runs."""
        sys.exit(0)

    # Register before instances start as a fallback for early signals.
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        while True:
            time.sleep(0.5)
            if all(p.poll() is not None for p in all_procs):
                break
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        _stop_uvicorn_instances(runner_procs)
        _stop_uvicorn_instances(assistant_procs)
        if celery_procs:
            print("[run.py] Stopping Celery workers ...")
            _stop_celery(celery_procs)
