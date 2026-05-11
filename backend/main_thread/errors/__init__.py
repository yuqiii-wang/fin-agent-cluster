"""backend.main_thread.errors — error codes for main thread operations.

Error codes are used in logs and returned to the UI to help locate errors.
"""

MAIN_THREAD_LOCK_CONFLICT = "MT_LOCK_CONFLICT"
MAIN_THREAD_LOCK_STOLEN = "MT_LOCK_STOLEN"
MAIN_THREAD_LOCK_LOST = "MT_LOCK_LOST"
MAIN_THREAD_DISPATCH_FAILED = "MT_DISPATCH_FAILED"
MAIN_THREAD_RECOVERY_FAILED = "MT_RECOVERY_FAILED"
MAIN_THREAD_ALREADY_RUNNING = "MT_ALREADY_RUNNING"
MAIN_THREAD_STEAL_RACE = "MT_STEAL_RACE"

MAIN_THREAD_ERRORS: dict[str, str] = {
    MAIN_THREAD_LOCK_CONFLICT: (
        "Thread is owned by another live main thread; retry the request"
    ),
    MAIN_THREAD_LOCK_STOLEN: (
        "Stolen lock from dead main thread and dispatching recovery run"
    ),
    MAIN_THREAD_LOCK_LOST: (
        "Lock renewal failed — ownership lost; aborting zombie graph run and "
        "marking orphaned tasks as wrong; new owner will complete the thread"
    ),
    MAIN_THREAD_DISPATCH_FAILED: (
        "Failed to dispatch graph run for thread"
    ),
    MAIN_THREAD_RECOVERY_FAILED: (
        "Failed to recover running thread on startup"
    ),
    MAIN_THREAD_ALREADY_RUNNING: (
        "Thread graph is already running on this main thread instance"
    ),
    MAIN_THREAD_STEAL_RACE: (
        "CAS steal failed — another instance already stole the lock; "
        "routing to the new owner"
    ),
}

__all__ = [
    "MAIN_THREAD_LOCK_CONFLICT",
    "MAIN_THREAD_LOCK_STOLEN",
    "MAIN_THREAD_LOCK_LOST",
    "MAIN_THREAD_DISPATCH_FAILED",
    "MAIN_THREAD_RECOVERY_FAILED",
    "MAIN_THREAD_ALREADY_RUNNING",
    "MAIN_THREAD_STEAL_RACE",
    "MAIN_THREAD_ERRORS",
]
