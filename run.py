"""Run the FastAPI server with proper Windows asyncio configuration."""
import asyncio
import atexit
import os
import signal
import subprocess
import sys
import uvicorn
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


def _start_celery(concurrency: int = 4) -> list[subprocess.Popen]:
    """Start Celery worker(s) and beat scheduler as subprocesses.

    Pool is ``gevent`` on Windows (prefork is unreliable there) and
    ``prefork`` on Unix (true OS-process isolation, better CPU utilisation).
    Beat is embedded on Unix (``--beat``) and a separate subprocess on Windows.

    Returns:
        List of :class:`subprocess.Popen` handles to pass to :func:`_stop_celery`.
    """
    import time
    is_windows = sys.platform == "win32"
    pool = "gevent" if is_windows else "prefork"
    env = os.environ.copy()
    procs: list[subprocess.Popen] = []

    worker_cmd = [
        sys.executable, "-m", "celery",
        "-A", "backend.streaming.celery_app.celery_app",
        "worker",
        "-Q", "celery",
        "-n", f"main-{os.getpid()}@%h",
        f"--concurrency={concurrency}",
        f"--pool={pool}",
        "--loglevel=info",
    ]
    # Unix prefork: stateless polling workers need no cluster coordination.
    if not is_windows:
        worker_cmd += ["--without-gossip", "--without-mingle"]

    if not is_windows:
        worker_cmd.append("--beat")

    # Windows: isolate from uvicorn's CTRL_C_EVENT on hot-reload.
    _creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if is_windows else 0

    print(f"[run.py] Starting Celery worker (concurrency={concurrency}, pool={pool}) ...")
    procs.append(subprocess.Popen(worker_cmd, env=env, creationflags=_creation_flags))

    # Windows requires beat as a separate process.
    if is_windows:
        beat_cmd = [
            sys.executable, "-m", "celery",
            "-A", "backend.streaming.celery_app.celery_app",
            "beat",
            "--loglevel=info",
        ]
        print("[run.py] Starting Celery beat (Windows separate process) ...")
        procs.append(subprocess.Popen(beat_cmd, env=env, creationflags=_creation_flags))

    time.sleep(2)
    return procs


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


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run the FastAPI server.")
    parser.add_argument("--no-proxy", action="store_true", help="Disable the use of the proxy even if configured.")
    parser.add_argument("--no-celery", action="store_true", help="Skip starting Celery workers (FastAPI fallback threads will be used instead).")
    parser.add_argument("--celery-concurrency", type=int, default=4, metavar="N", help="Number of Celery worker threads (default: 4).")
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

    def _shutdown(signum, frame) -> None:  # type: ignore[misc]
        """Forward SIGTERM/SIGINT to a clean sys.exit so atexit runs."""
        sys.exit(0)

    # Register before uvicorn.run() as a fallback for early signals.
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        uvicorn.run(
            "backend.main:app",
            host="127.0.0.1",  # loopback only — Kong reaches it via host.docker.internal
            port=settings.FASTAPI_PORT,
            reload=True,
            reload_dirs=["backend"],
            workers=1,
            log_config=get_logging_config(),
        )
    finally:
        if celery_procs:
            print("[run.py] Stopping Celery workers ...")
            _stop_celery(celery_procs)
