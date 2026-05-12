"""Centralised logging configuration for the fin-trading-cluster backend.

Logger hierarchy and file routing
----------------------------------
Component              Logger prefix                        Output file
────────────────────   ──────────────────────────────────   ─────────────────────
FastAPI routes         backend.api                          logs/api.log
Centrifugo client      backend.centrifugo_mq                logs/centrifugo.log
Database / PostgreSQL  backend.db.postgres                  logs/db.log
Database / Redis       backend.db.redis                     logs/db.log
Main thread            backend.main_thread                  logs/graph.log
LangGraph + agents     backend.langgraph                    logs/graph.log
LLM providers          backend.llm                          logs/llm.log
Market / news data     backend.resources                    logs/resources.log
Redis Streams / MQ     backend.celery_task                  logs/streaming.log
Celery workers         celery                               logs/streaming.log
User auth              backend.users                        logs/users.log
Uvicorn HTTP access    uvicorn.access                       console only
Uvicorn errors         uvicorn / uvicorn.error              console only

All components also write to the console (stdout) and to a catch-all
``logs/app.log`` (WARNING+ only) for post-mortem diagnosis.

Usage
-----
Call :func:`configure_logging` once at process start, then pass
:func:`get_logging_config` as the ``log_config`` kwarg to
``uvicorn.run()`` so uvicorn uses the same config dict instead of its
own defaults::

    from backend.log_config import configure_logging, get_logging_config

    configure_logging()
    uvicorn.run("backend.main:app", ..., log_config=get_logging_config())
"""

from __future__ import annotations

import json
import logging
import logging.config
import logging.handlers
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Project root is two levels up from this file (backend/log_config.py → root)
_LOG_DIR: Path = Path(__file__).resolve().parent.parent / "logs"

# ---------------------------------------------------------------------------
# ANSI colour helpers — applied per log level in the console formatter.
# No external dependencies; just escape codes.
# ---------------------------------------------------------------------------
_RESET = "\x1b[0m"
_LEVEL_COLOURS: dict[str, str] = {
    "DEBUG":    "\x1b[38;5;244m",   # dim grey
    "INFO":     "\x1b[36m",          # cyan
    "WARNING":  "\x1b[33m",          # yellow
    "ERROR":    "\x1b[31m",          # red
    "CRITICAL": "\x1b[1;31m",        # bold red
}

# Short component label derived from logger namespace.
# Checked longest-first so the most-specific prefix wins.
_COMPONENT_LABELS: list[tuple[str, str]] = [
    ("backend.langgraph.nodes",                      "Graph/Nodes"),
    ("backend.langgraph.tasks",                      "Graph/Tasks"),
    ("backend.langgraph.lifecycle",                  "Graph/Lifecycle"),
    ("backend.langgraph",                            "LangGraph"),
    ("backend.main_thread",                          "MainThread"),
    ("backend.centrifugo_mq.sse_notification",       "Centrifugo/SSE"),
    ("backend.centrifugo_mq.llm_tokens",             "Centrifugo/LLM"),
    ("backend.centrifugo_mq",                        "Centrifugo"),
    ("backend.db.postgres",                          "DB/Postgres"),
    ("backend.db.redis",                             "DB/Redis"),
    ("backend.db",                                   "DB"),
    ("backend.llm.providers",                        "LLM/Providers"),
    ("backend.llm",                                  "LLM"),
    ("backend.resources.news",                       "Resources/News"),
    ("backend.resources.stats",                      "Resources/Stats"),
    ("backend.resources",                            "Resources"),
    ("backend.sse_notifications",                    "SSE/Notify"),
    ("backend.celery_task.workers",                  "Stream/Workers"),
    ("backend.celery_task",                          "Streaming"),
    ("backend.api",                                  "API"),
    ("backend.users",                                "Users"),
    ("backend",                                      "Backend"),
    ("uvicorn.access",                               "HTTP"),
    ("uvicorn",                                      "Uvicorn"),
    ("celery.app.trace",                             "Celery/Trace"),
    ("celery",                                       "Celery"),
]


def _resolve_component(name: str) -> str:
    """Return the short component label for *name*.

    Walks ``_COMPONENT_LABELS`` in order (longest prefix first) and returns the
    first matching label.  Falls back to the last segment of the logger name.

    Args:
        name: Fully-qualified logger name (``__name__``).

    Returns:
        Short component tag, e.g. ``'Agent/Market'``.
    """
    for prefix, label in _COMPONENT_LABELS:
        if name == prefix or name.startswith(prefix + "."):
            return label
    return name.rsplit(".", 1)[-1] if "." in name else name


class ComponentFormatter(logging.Formatter):
    """Console formatter that adds a coloured level indicator and a component tag.

    Output format::

        10:23:45 | INFO     | API              | Created guest user abc123
        10:23:46 | WARNING  | LLM/Providers    | Ollama not reachable — retrying
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format *record* with level colour and component tag.

        Args:
            record: The log record to format.

        Returns:
            Formatted string ready for console output.
        """
        colour = _LEVEL_COLOURS.get(record.levelname, "")
        level_tag = f"{colour}{record.levelname:<8}{_RESET}"
        component = _resolve_component(record.name)
        record.__dict__["component"] = f"{component:<16}"
        record.__dict__["level_tag"] = level_tag
        return super().format(record)


class JsonFileFormatter(logging.Formatter):
    """JSON-lines formatter for file handlers consumed by Promtail/Loki.

    Each log record is emitted as a single-line JSON object with fields:
    ``timestamp`` (ISO-8601), ``level``, ``logger``, ``component``, ``message``,
    and optionally ``exception``.

    Example output::

        {"timestamp": "2024-01-01T10:23:45.123456", "level": "INFO",
         "logger": "backend.api", "component": "API", "message": "Created guest user"}
    """

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:  # type: ignore[override]
        """Return ISO-8601 timestamp with microseconds.

        Overrides the base implementation to use :class:`datetime` instead of
        ``time.strftime``, because ``%f`` (microseconds) is not supported by
        the Windows C-runtime ``strftime``.

        Always emits UTC so that Loki (which also runs in UTC) accepts the
        entries without "timestamp too new" rejections.

        Args:
            record:  The log record.
            datefmt: Ignored; always uses ISO-8601 with microseconds in UTC.

        Returns:
            Timestamp string, e.g. ``'2024-01-01T10:23:45.123456'``.
        """
        return datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")

    def format(self, record: logging.LogRecord) -> str:
        """Serialise *record* to a JSON line.

        Args:
            record: The log record to format.

        Returns:
            A single JSON-encoded string (no trailing newline).
        """
        record.message = record.getMessage()
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)

        payload: dict[str, str] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "component": _resolve_component(record.name),
            "message": record.message,
        }
        if record.exc_text:
            payload["exception"] = record.exc_text

        return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Resilient file handler
# ---------------------------------------------------------------------------


class _SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler that re-creates the parent directory if deleted at runtime.

    The default handler raises ``FileNotFoundError`` in ``shouldRollover`` when
    the log directory is removed after process start (e.g. by ``setup.sh``
    running ``rm -rf logs/``).  This subclass recreates the directory before
    every ``_open()`` call so the handler self-heals without crashing.
    """

    def _open(self) -> "IO[str]":
        """Open the log file, creating the parent directory if necessary."""
        Path(self.baseFilename).parent.mkdir(parents=True, exist_ok=True)
        return super()._open()


# ---------------------------------------------------------------------------
# Per-instance port injection
# ---------------------------------------------------------------------------


class ServerPortFilter(logging.Filter):
    """Inject the listening port of this uvicorn instance into every log record.

    Reads ``FASTAPI_PORT`` from the environment at emit time so the correct
    value is used even when :func:`configure_logging` is called before the
    env var is set (e.g. during module import before ``run.py`` sets it).
    Falls back to ``"?"`` if the variable is absent (e.g. in tests or direct
    ``uvicorn`` invocations without ``run.py``).
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.server_port = os.environ.get("FASTAPI_PORT", "?")
        return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _log_dir() -> Path:
    """Return the log directory path, creating it if necessary.

    ``Path.mkdir(exist_ok=True)`` only suppresses *FileExistsError* when the
    path is already a directory.  If the path exists but is a plain file,
    broken symlink, or a Windows reparse point that WSL exposes as a non-
    directory entry, it re-raises.  We handle that explicitly.

    Returns:
        Resolved :class:`pathlib.Path` to the ``logs/`` directory.
    """
    if _LOG_DIR.is_dir():
        return _LOG_DIR
    if _LOG_DIR.exists() or _LOG_DIR.is_symlink():
        # A file or broken symlink is blocking the directory; remove it.
        _LOG_DIR.unlink()
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    return _LOG_DIR


def get_logging_config() -> dict[str, Any]:
    """Return a ``logging.config.dictConfig``-compatible dict.

    Includes all application loggers plus uvicorn's required loggers so this
    dict can be passed directly as ``log_config`` to ``uvicorn.run()``.

    Returns:
        Full logging configuration dict.
    """
    log_dir = str(_log_dir())

    def _file(filename: str) -> dict[str, Any]:
        """Build a RotatingFileHandler entry for *filename*.

        Args:
            filename: Base filename inside ``logs/``.

        Returns:
            Handler config dict.
        """
        return {
            "class": "backend.log_config._SafeRotatingFileHandler",
            "formatter": "file",
            "filename": f"{log_dir}/{filename}",
            "maxBytes": 10 * 1024 * 1024,  # 10 MB per file
            "backupCount": 5,               # keeps .log .log.1 … .log.5 → all matched by *.log*
            "encoding": "utf-8",
            "delay": True,                  # don't create the file until first write
        }

    return {
        "version": 1,
        "disable_existing_loggers": False,

        # ── Formatters ─────────────────────────────────────────────────────
        "formatters": {
            "console": {
                "()": "backend.log_config.ComponentFormatter",
                "format": "%(asctime)s | %(level_tag)s | %(component)s | %(message)s",
                "datefmt": "%H:%M:%S",
            },
            "file": {
                "()": "backend.log_config.JsonFileFormatter",
            },
            # Uvicorn's own access formatter — preserves coloured status codes.
            # [%(server_port)s] is injected by ServerPortFilter (added to uvicorn_access_h)
            # so each line shows which FastAPI instance handled the request.
            "uvicorn_access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": "%(levelprefix)s [%(server_port)s] %(client_addr)s - \"%(request_line)s\" %(status_code)s",
            },
            "uvicorn_default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(message)s",
                "use_colors": None,
            },
        },

        # ── Filters ────────────────────────────────────────────────────────
        "filters": {
            "health_check_throttle": {
                "()": "backend.api.log_filters.HealthCheckThrottleFilter",
            },
            "server_port_inject": {
                "()": "backend.log_config.ServerPortFilter",
            },
        },

        # ── Handlers ───────────────────────────────────────────────────────
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "console",
                "stream": "ext://sys.stdout",
                "level": "INFO",
            },
            "app_file": {
                **_file("app.log"),
                "level": "WARNING",  # catch-all for unexpected warnings
            },
            "api_file":                {**_file("api.log"),                "level": "INFO"},
            "centrifugo_file":          {**_file("centrifugo.log"),          "level": "INFO"},
            "db_file":                 {**_file("db.log"),                 "level": "INFO"},
            "graph_file":              {**_file("graph.log"),              "level": "INFO"},
            "llm_file":                {**_file("llm.log"),                "level": "INFO"},
            "resources_file":          {**_file("resources.log"),          "level": "INFO"},
            "sse_notifications_file":  {**_file("sse_notifications.log"),  "level": "INFO"},
            "streaming_file":          {**_file("streaming.log"),          "level": "INFO"},
            "users_file":              {**_file("users.log"),              "level": "INFO"},
            # Uvicorn-specific handlers (required by uvicorn internals)
            "uvicorn_default_h": {
                "class": "logging.StreamHandler",
                "formatter": "uvicorn_default",
                "stream": "ext://sys.stderr",
            },
            # Dedicated console handler for Celery — filter attached programmatically
            # by celery_engine._configure_worker_logging after configure_logging() runs.
            "celery_console": {
                "class": "logging.StreamHandler",
                "formatter": "console",
                "stream": "ext://sys.stdout",
                "level": "INFO",
            },
            "uvicorn_access_h": {
                "class": "logging.StreamHandler",
                "formatter": "uvicorn_access",
                "stream": "ext://sys.stdout",
                "filters": ["health_check_throttle", "server_port_inject"],
            },
        },

        # ── Loggers ────────────────────────────────────────────────────────
        "loggers": {
            # ── Application component loggers ──────────────────────────────
            "backend.api": {
                "handlers": ["console", "api_file", "app_file"],
                "level": "INFO",
                "propagate": False,
            },
            "backend.centrifugo_mq": {
                "handlers": ["console", "centrifugo_file", "app_file"],
                "level": "INFO",
                "propagate": False,
            },
            "backend.db.postgres": {
                "handlers": ["console", "db_file", "app_file"],
                "level": "INFO",
                "propagate": False,
            },
            "backend.db.redis": {
                "handlers": ["console", "db_file", "app_file"],
                "level": "INFO",
                "propagate": False,
            },
            "backend.main_thread": {
                "handlers": ["console", "graph_file", "app_file"],
                "level": "INFO",
                "propagate": False,
            },
            "backend.langgraph": {
                "handlers": ["console", "graph_file", "app_file"],
                "level": "INFO",
                "propagate": False,
            },
            "backend.sse_notifications": {
                "handlers": ["console", "sse_notifications_file", "app_file"],
                "level": "INFO",
                "propagate": False,
            },
            "backend.llm": {
                "handlers": ["console", "llm_file", "app_file"],
                "level": "INFO",
                "propagate": False,
            },
            "backend.resources": {
                "handlers": ["console", "resources_file", "app_file"],
                "level": "INFO",
                "propagate": False,
            },
            "backend.celery_task": {
                "handlers": ["console", "streaming_file", "app_file"],
                "level": "INFO",
                "propagate": False,
            },
            "backend.celery_task.workers": {
                # Explicit entry so Celery prefork worker sub-processes route
                # task logs directly to streaming.log
                # without relying on propagation through backend.celery_task.
                "handlers": ["console", "streaming_file", "app_file"],
                "level": "INFO",
                "propagate": False,
            },
            "backend.users": {
                "handlers": ["console", "users_file", "app_file"],
                "level": "INFO",
                "propagate": False,
            },
            # Catch-all for any other backend.* module not covered above
            "backend": {
                "handlers": ["console", "app_file"],
                "level": "INFO",
                "propagate": False,
            },

            # ── Uvicorn ────────────────────────────────────────────────────
            "uvicorn": {
                "handlers": ["uvicorn_default_h"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": ["uvicorn_default_h"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["uvicorn_access_h"],
                "level": "INFO",
                "propagate": False,
            },

            # ── Celery ─────────────────────────────────────────────────────
            "celery": {
                "handlers": ["celery_console", "streaming_file", "app_file"],
                "level": "INFO",
                "propagate": False,
            },
            # celery.app.trace logs every task execution at INFO — noisy in prod
            "celery.app.trace": {
                "handlers": ["streaming_file"],
                "level": "WARNING",
                "propagate": False,
            },

            # ── Third-party noise reduction ────────────────────────────────
            "httpx":             {"level": "WARNING", "propagate": True},
            "httpcore":          {"level": "WARNING", "propagate": True},
            "langchain":         {"level": "WARNING", "propagate": True},
            "langchain_core":    {"level": "WARNING", "propagate": True},
            "langgraph":         {"level": "WARNING", "propagate": True},
            "openai":            {"level": "WARNING", "propagate": True},
            "yfinance":          {"level": "WARNING", "propagate": True},
            "akshare":           {"level": "WARNING", "propagate": True},
            "urllib3":           {"level": "WARNING", "propagate": True},
            "asyncio":           {"level": "WARNING", "propagate": True},
            "sqlalchemy.engine": {"level": "WARNING", "propagate": True},
        },

        # ── Root logger ────────────────────────────────────────────────────
        # Catches anything not explicitly routed above (third-party, etc.)
        "root": {
            "handlers": ["console", "app_file"],
            "level": "WARNING",
        },
    }


def configure_logging() -> None:
    """Apply the logging configuration to the current process.

    Safe to call multiple times (dictConfig is idempotent when
    ``disable_existing_loggers`` is ``False``).  Call this once at process
    start, before any code that emits log records.
    """
    logging.config.dictConfig(get_logging_config())
