"""Start on-demand Celery workers (completion + stream pools)."""
import os
import subprocess
import sys
import time
import warnings


def wait_for_ondemand_workers(
    timeout_per_check: float = 3.0,
    max_retries: int = 20,
    retry_interval_s: float = 2.0,
) -> bool:
    """Poll until at least one on-demand Celery worker responds to a ping.

    Args:
        timeout_per_check: Seconds to wait for worker ping replies per attempt.
        max_retries:       Maximum number of ping attempts.
        retry_interval_s:  Seconds between failed attempts (polling interval).

    Returns:
        ``True`` when at least one worker is reachable; ``False`` after
        *max_retries* without a response.
    """
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


def start_celery_cluster(
    runner_count: int,
    completion_workers_per_instance: int = 2,
    completion_worker_concurrency: int = 4,
    stream_workers_per_instance: int = 2,
    stream_worker_concurrency: int = 4,
) -> list[subprocess.Popen]:
    """Start completion and stream Celery workers with separate queues.

    Completion workers consume ``celery_ondemand_*`` queues (fast tasks:
    analyze_query, read_stats, read_news, merge_results — each <500ms).

    Stream workers consume ``celery_stream_*`` queues (slow tasks:
    stream_llm — holds a slot for the full LLM stream, e.g. 10s).

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
