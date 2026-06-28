"""Main orchestrator: wires celery + uvicorn + signal handling."""
import atexit
import os
import signal
import subprocess
import sys
import threading
import time

from backend.config import get_settings
from backend.log_config import configure_logging, get_logging_config

from start.celery_cluster import start_celery_cluster, wait_for_ondemand_workers
from start.docker_check import ensure_docker_running
from start.log_config_writer import write_log_config
from start.proxy_config import configure_proxy
from start.shutdown_cancel import run_shutdown_cancel
from start.uvicorn_mgr import start_uvicorn_instances, stop_uvicorn_instances
from start.windows_job import assign_to_job, create_job_object


def _warmup_llm(settings) -> None:
    """Fire the correct LLM provider warmup based on settings.LLM_PROVIDER."""
    provider = settings.LLM_PROVIDER.strip().lower()
    if provider == "ollama":
        from _shared.llm.providers.ollama.warmup import warmup_ollama
        threading.Thread(target=warmup_ollama, daemon=True, name="ollama-warmup").start()
    elif provider != "mock":
        from _shared.llm.validate import ping_llm
        ping_llm()


def start_app(no_proxy: bool = False) -> int:
    """Start Celery workers + uvicorn instances and supervise them.

    Args:
        no_proxy: When ``True``, skip the configured outbound proxy entirely.

    Returns:
        Process exit code (``0`` on clean shutdown).
    """
    settings = get_settings()
    print("[run.py] Settings:")
    for _k, _v in settings.model_dump().items():
        print(f"  {_k} = {_v}")

    configure_proxy(None if no_proxy else settings.HTTP_PROXY)

    ensure_docker_running()

    if sys.platform == "win32":
        # psycopg requires SelectorEventLoop on Windows.
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    configure_logging()

    _job = create_job_object()  # kills children automatically on parent exit

    celery_procs: list[subprocess.Popen] = []
    if settings.CELERY_WORKERS_PER_INSTANCE > 0 or settings.CELERY_STREAM_WORKERS_PER_INSTANCE > 0:
        celery_procs = start_celery_cluster(
            runner_count=settings.RUNNER_INSTANCE_COUNT,
            completion_workers_per_instance=settings.CELERY_WORKERS_PER_INSTANCE,
            completion_worker_concurrency=settings.CELERY_WORKER_CONCURRENCY,
            stream_workers_per_instance=settings.CELERY_STREAM_WORKERS_PER_INSTANCE,
            stream_worker_concurrency=settings.CELERY_STREAM_WORKER_CONCURRENCY,
        )
        for _p in celery_procs:
            assign_to_job(_job, _p)
        atexit.register(stop_uvicorn_instances, celery_procs)
        # Gate main threads on Celery readiness so tasks are never queued to
        # an empty broker. A missing worker causes ~64 s task queue delays and
        # a subsequent "node already terminal" race on recovery.
        wait_for_ondemand_workers()

    _warmup_llm(settings)

    log_config_path = write_log_config(get_logging_config())
    atexit.register(lambda: os.unlink(log_config_path) if os.path.exists(log_config_path) else None)

    # Build per-instance env overrides: each instance knows its own port via
    # MAIN_THREAD_PORT so the ownership lock stores the correct port.
    _per_instance_env = [
        {"MAIN_THREAD_PORT": str(settings.FASTAPI_PORT + i)}
        for i in range(settings.RUNNER_INSTANCE_COUNT)
    ]

    # Start main thread instances (FastAPI + embedded graph runner).
    runner_procs = start_uvicorn_instances(
        base_port=settings.FASTAPI_PORT,
        count=settings.RUNNER_INSTANCE_COUNT,
        app_module="backend.main:app",
        log_config_path=log_config_path,
        extra_env_per_instance=_per_instance_env,
    )
    for _p in runner_procs:
        assign_to_job(_job, _p)
    atexit.register(stop_uvicorn_instances, runner_procs)

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
        run_shutdown_cancel()
        stop_uvicorn_instances(runner_procs)
        if celery_procs:
            print("[run.py] Stopping Celery workers ...")
            stop_uvicorn_instances(celery_procs)

    return 0
