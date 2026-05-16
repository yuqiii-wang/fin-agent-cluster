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



def _start_uvicorn_instances(
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


# Celery workers have the same lifecycle as uvicorn instances.
_stop_celery = _stop_uvicorn_instances


def _create_job_object() -> "int | None":
    """Create a Windows Job Object with KILL_ON_JOB_CLOSE (no-op on Unix)."""
    if sys.platform != "win32":
        return None
    import ctypes

    kernel32 = ctypes.windll.kernel32
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None

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
        job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info),
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
    """Write *log_config* dict to a temp JSON file for uvicorn ``--log-config``.

    Returns:
        Absolute path to the written temp file.
    """
    fd, path = tempfile.mkstemp(suffix=".json", prefix="uvicorn_log_")
    with os.fdopen(fd, "w") as f:
        json.dump(log_config, f)
    return path


async def _shutdown_cancel_all() -> None:
    """Cancel every active thread in the DB with SSE notifications.

    Runs in a fresh ``asyncio.run()`` event loop from the process-manager
    context (i.e. *not* inside a FastAPI instance).  Uses only the shared DB
    and Centrifugo connections that are reachable from the parent process.

    Errors are logged but never raised — shutdown must complete regardless.
    """
    import logging
    _log = logging.getLogger("run.py.shutdown")
    try:
        from backend.db.postgres import raw_conn
        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(
                "SELECT thread_id FROM fin_agents.user_queries"
                " WHERE status NOT IN ('completed', 'failed', 'cancelled')"
            )
            rows = await cur.fetchall()
        thread_ids = [r["thread_id"] for r in rows]
    except Exception as exc:  # noqa: BLE001
        _log.error("[run.py] shutdown: failed to query active threads: %s", exc)
        return

    if not thread_ids:
        return

    print(f"[run.py] shutdown: cancelling {len(thread_ids)} active thread(s) with SSE …")
    from backend.langgraph.lifecycle.threads import cancel_thread
    for thread_id in thread_ids:
        try:
            await cancel_thread(thread_id, reason="shutdown")
        except Exception as exc:  # noqa: BLE001
            _log.error(
                "[run.py] shutdown: cancel_thread failed thread_id=%s: %s",
                thread_id, exc,
            )


def _wait_for_ondemand_workers(
    timeout_per_check: float = 3.0,
    max_retries: int = 20,
    retry_interval_s: float = 2.0,
) -> bool:
    """Poll until at least one on-demand Celery worker responds to a ping.

    Blocks the run.py main thread while waiting.  Called after
    ``_start_celery_cluster`` and before the main thread FastAPI instances
    start so graphs are never dispatched to an empty broker queue.

    Args:
        timeout_per_check: Seconds to wait for worker ping replies per attempt.
        max_retries:       Maximum number of ping attempts.
        retry_interval_s:  Seconds between failed attempts (polling interval).

    Returns:
        ``True`` when at least one worker is reachable; ``False`` after
        *max_retries* without a response.
    """
    import warnings

    try:
        from celery.app.control import DuplicateNodenameWarning
    except ImportError:
        DuplicateNodenameWarning = Warning  # type: ignore[misc,assignment]

    from backend.celery_task.celery_engine import celery_engine

    for attempt in range(1, max_retries + 1):
        try:
            inspect = celery_engine.control.inspect(timeout=timeout_per_check)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DuplicateNodenameWarning)
                result = inspect.ping()
            if result:
                if attempt > 1:
                    print(
                        f"[run.py] On-demand Celery workers ready"
                        f" (attempt {attempt}/{max_retries})"
                    )
                return True
        except Exception as exc:
            print(
                f"[run.py] Celery ping attempt {attempt}/{max_retries} error: {exc}"
            )

        if attempt < max_retries:
            print(
                f"[run.py] Waiting for on-demand Celery workers ..."
                f" (attempt {attempt}/{max_retries})"
            )
            time.sleep(retry_interval_s)

    print(
        f"[run.py] WARNING: on-demand Celery workers not ready after"
        f" {max_retries} attempts — graph runners may dispatch tasks"
        f" to an empty queue"
    )
    return False


def _start_celery_cluster(
    runner_count: int,
    completion_workers_per_instance: int = 2,
    completion_worker_concurrency: int = 4,
    stream_workers_per_instance: int = 2,
    stream_worker_concurrency: int = 8,
) -> list[subprocess.Popen]:
    """Start completion and stream Celery workers with separate queues.

    Completion workers consume ``celery_ondemand_*`` queues (fast tasks:
    analyze_query, read_stats, read_news, merge_results — each <500ms).

    Stream workers consume ``celery_stream_*`` queues (slow tasks:
    stream_conclusion — holds a slot for the full LLM stream, e.g. 10s).

    Keeping the pools separate means fast completion tasks are never blocked
    waiting for stream slots and vice versa.  Peak streaming concurrency =
    ``runner_count * stream_workers_per_instance * stream_worker_concurrency``.

    Args:
        runner_count:                   Number of runner FastAPI instances.
        completion_workers_per_instance: Completion workers per runner instance.
        completion_worker_concurrency:  Prefork children per completion worker.
        stream_workers_per_instance:    Stream workers per runner instance.
        stream_worker_concurrency:      Prefork children per stream worker.

    Returns:
        List of :class:`subprocess.Popen` handles for all started workers.
    """
    is_windows = sys.platform == "win32"
    pool = "solo" if is_windows else "prefork"
    _creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if is_windows else 0

    from backend.celery_task.config import all_ondemand_queues, all_stream_queues  # noqa: PLC0415
    _completion_queues = ",".join(all_ondemand_queues())
    _stream_queues = ",".join(all_stream_queues())

    procs: list[subprocess.Popen] = []

    # ── Completion workers ────────────────────────────────────────────────
    total_completion = runner_count * completion_workers_per_instance
    for i in range(total_completion):
        instance_idx = i // completion_workers_per_instance
        worker_idx = i % completion_workers_per_instance
        hostname = f"completion-{instance_idx}-{worker_idx}@%h"
        cmd = [
            sys.executable, "-m", "celery",
            "-A", "backend.celery_task.celery_engine",
            "worker",
            "--hostname", hostname,
            "--concurrency", str(completion_worker_concurrency),
            "--pool", pool,
            "--loglevel", "info",
            "-Q", _completion_queues,
        ]
        if not is_windows:
            cmd += ["--without-gossip", "--without-mingle"]
        print(
            f"[run.py] Starting completion worker {i + 1}/{total_completion}"
            f" (runner_instance={instance_idx}, worker={worker_idx}, pool={pool},"
            f" concurrency={completion_worker_concurrency}) ..."
        )
        procs.append(subprocess.Popen(cmd, env=os.environ.copy(), creationflags=_creation_flags))

    # ── Stream workers ────────────────────────────────────────────────────
    total_stream = runner_count * stream_workers_per_instance
    for i in range(total_stream):
        instance_idx = i // stream_workers_per_instance
        worker_idx = i % stream_workers_per_instance
        hostname = f"stream-{instance_idx}-{worker_idx}@%h"
        cmd = [
            sys.executable, "-m", "celery",
            "-A", "backend.celery_task.celery_engine",
            "worker",
            "--hostname", hostname,
            "--concurrency", str(stream_worker_concurrency),
            "--pool", pool,
            "--loglevel", "info",
            "-Q", _stream_queues,
        ]
        if not is_windows:
            cmd += ["--without-gossip", "--without-mingle"]
        print(
            f"[run.py] Starting stream worker {i + 1}/{total_stream}"
            f" (runner_instance={instance_idx}, worker={worker_idx}, pool={pool},"
            f" concurrency={stream_worker_concurrency}) ..."
        )
        procs.append(subprocess.Popen(cmd, env=os.environ.copy(), creationflags=_creation_flags))

    return procs


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run the FastAPI server.")
    parser.add_argument("--no-proxy", action="store_true", help="Disable the use of the proxy even if configured.")

    args = parser.parse_args()

    settings = get_settings()
    print("[run.py] Settings:")
    for _k, _v in settings.model_dump().items():
        print(f"  {_k} = {_v}")
    proxy_to_use = None if args.no_proxy else settings.HTTP_PROXY
    _configure_proxy(proxy_to_use)

    if sys.platform == "win32":
        # psycopg requires SelectorEventLoop on Windows.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    configure_logging()

    _job = _create_job_object()  # kills children automatically on parent exit

    celery_procs: list[subprocess.Popen] = []
    if settings.CELERY_WORKERS_PER_INSTANCE > 0 or settings.CELERY_STREAM_WORKERS_PER_INSTANCE > 0:
        celery_procs = _start_celery_cluster(
            runner_count=settings.RUNNER_INSTANCE_COUNT,
            completion_workers_per_instance=settings.CELERY_WORKERS_PER_INSTANCE,
            completion_worker_concurrency=settings.CELERY_WORKER_CONCURRENCY,
            stream_workers_per_instance=settings.CELERY_STREAM_WORKERS_PER_INSTANCE,
            stream_worker_concurrency=settings.CELERY_STREAM_WORKER_CONCURRENCY,
        )
        for _p in celery_procs:
            _assign_to_job(_job, _p)
        atexit.register(_stop_celery, celery_procs)
        # Gate main threads on Celery readiness so tasks are never queued to
        # an empty broker. A missing worker causes ~64 s task queue delays and
        # a subsequent "node already terminal" race on recovery.
        _wait_for_ondemand_workers()

    log_config_path = _write_log_config(get_logging_config())
    atexit.register(lambda: os.unlink(log_config_path) if os.path.exists(log_config_path) else None)

    # Build per-instance env overrides: each instance knows its own port via
    # MAIN_THREAD_PORT so the ownership lock stores the correct port.
    _per_instance_env = [
        {"MAIN_THREAD_PORT": str(settings.FASTAPI_PORT + i)}
        for i in range(settings.RUNNER_INSTANCE_COUNT)
    ]

    # Start main thread instances (FastAPI + embedded graph runner).
    runner_procs = _start_uvicorn_instances(
        base_port=settings.FASTAPI_PORT,
        count=settings.RUNNER_INSTANCE_COUNT,
        app_module="backend.main:app",
        log_config_path=log_config_path,
        extra_env_per_instance=_per_instance_env,
    )
    for _p in runner_procs:
        _assign_to_job(_job, _p)
    atexit.register(_stop_uvicorn_instances, runner_procs)

    all_procs = runner_procs

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
        # Cancel all active threads with SSE notification before killing workers
        # so the frontend receives cancelled events while Centrifugo is still up.
        try:
            asyncio.run(_shutdown_cancel_all())
        except Exception as _exc:  # noqa: BLE001
            print(f"[run.py] shutdown cancel error: {_exc}")
        _stop_uvicorn_instances(runner_procs)
        if celery_procs:
            print("[run.py] Stopping Celery workers ...")
            _stop_celery(celery_procs)
