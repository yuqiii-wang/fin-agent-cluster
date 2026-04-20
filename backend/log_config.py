"""Centralised logging configuration for the fin-trading-cluster backend.

Logger hierarchy and file routing
----------------------------------
Component              Logger prefix                        Output file
────────────────────   ──────────────────────────────────   ─────────────────────
FastAPI routes         backend.api                          logs/api.log
Database / PostgreSQL  backend.db.postgres                  logs/db.log
Database / Redis       backend.db.redis                     logs/db.log
LangGraph + agents     backend.graph                        logs/graph.log
LLM providers          backend.llm                          logs/llm.log
Market / news data     backend.resource_api                 logs/resource_api.log
Redis Streams / MQ     backend.streaming                    logs/streaming.log
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
    ("backend.graph.agents.decision_maker",         "Agent/Decision"),
    ("backend.graph.agents.market_data",             "Agent/Market"),
    ("backend.graph.agents.query_optimizer",         "Agent/QueryOpt"),
    ("backend.graph.agents.perf_test",               "PerfTest"),
    ("backend.graph.agents",                         "Graph/Agents"),
    ("backend.graph.utils",                          "Graph/Utils"),
    ("backend.graph",                                "Graph"),
    ("backend.db.postgres",                          "DB/Postgres"),
    ("backend.db.redis",                             "DB/Redis"),
    ("backend.db",                                   "DB"),
    ("backend.llm.providers",                        "LLM/Providers"),
    ("backend.llm",                                  "LLM"),
    ("backend.resource_api.quant_api",               "ResAPI/Quant"),
    ("backend.resource_api.news_api",                "ResAPI/News"),
    ("backend.resource_api",                         "ResAPI"),
    ("backend.sse_notifications.agent_tasks",        "SSE/Tasks"),
    ("backend.sse_notifications.perf_test",          "SSE/PerfTest"),
    ("backend.sse_notifications.node_io",            "SSE/NodeIO"),
    ("backend.sse_notifications",                    "SSE/Notify"),
    ("backend.streaming.workers",                    "Stream/Workers"),
    ("backend.streaming",                            "Streaming"),
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
# Public API
# ---------------------------------------------------------------------------


def _log_dir() -> Path:
    """Return the log directory path, creating it if necessary.

    Returns:
        Resolved :class:`pathlib.Path` to the ``logs/`` directory.
    """
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
            "class": "logging.handlers.RotatingFileHandler",
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
            "uvicorn_access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": "%(levelprefix)s %(client_addr)s - \"%(request_line)s\" %(status_code)s",
            },
            "uvicorn_default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(message)s",
                "use_colors": None,
            },
        },

        # ── Filters ────────────────────────────────────────────────────────
        "filters": {
            "celery_task_summary": {
                "()": "backend.streaming.log_filters.CeleryTaskSummaryFilter",
            },
            "health_check_throttle": {
                "()": "backend.api.log_filters.HealthCheckThrottleFilter",
            },
        },

        # ── Handlers ───────────────────────────────────────────────────────
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "console",
                "stream": "ext://sys.stdout",
                "level": "DEBUG",
            },
            "app_file": {
                **_file("app.log"),
                "level": "WARNING",  # catch-all for unexpected warnings
            },
            "api_file":                {**_file("api.log"),                "level": "DEBUG"},
            "db_file":                 {**_file("db.log"),                 "level": "DEBUG"},
            "graph_file":              {**_file("graph.log"),              "level": "DEBUG"},
            "perf_test_file":          {**_file("perf_test.log"),          "level": "DEBUG"},
            "llm_file":                {**_file("llm.log"),                "level": "DEBUG"},
            "resource_api_file":       {**_file("resource_api.log"),       "level": "DEBUG"},
            "sse_notifications_file":  {**_file("sse_notifications.log"),  "level": "DEBUG"},
            "streaming_file":          {**_file("streaming.log"),          "level": "DEBUG"},
            "users_file":              {**_file("users.log"),              "level": "DEBUG"},
            # Uvicorn-specific handlers (required by uvicorn internals)
            "uvicorn_default_h": {
                "class": "logging.StreamHandler",
                "formatter": "uvicorn_default",
                "stream": "ext://sys.stderr",
            },
            # Dedicated console handler for Celery — throttles task noise
            "celery_console": {
                "class": "logging.StreamHandler",
                "formatter": "console",
                "stream": "ext://sys.stdout",
                "level": "DEBUG",
                "filters": ["celery_task_summary"],
            },
            "uvicorn_access_h": {
                "class": "logging.StreamHandler",
                "formatter": "uvicorn_access",
                "stream": "ext://sys.stdout",
                "filters": ["health_check_throttle"],
            },
        },

        # ── Loggers ────────────────────────────────────────────────────────
        "loggers": {
            # ── Application component loggers ──────────────────────────────
            "backend.api": {
                "handlers": ["console", "api_file", "app_file"],
                "level": "DEBUG",
                "propagate": False,
            },
            "backend.db.postgres": {
                "handlers": ["console", "db_file", "app_file"],
                "level": "INFO",
                "propagate": False,
            },
            "backend.db.redis": {
                # Promoted to DEBUG to trace Redis publish/subscribe events.
                "handlers": ["console", "db_file", "app_file"],
                "level": "DEBUG",
                "propagate": False,
            },
            "backend.graph.agents.perf_test": {
                # Separate file so perf-test traces can be grepped without
                # wading through the full graph log.
                "handlers": ["console", "perf_test_file", "graph_file", "app_file"],
                "level": "DEBUG",
                "propagate": False,
            },
            "backend.graph": {
                "handlers": ["console", "graph_file", "app_file"],
                "level": "DEBUG",
                "propagate": False,
            },
            "backend.sse_notifications": {
                # Critical notification path — every task lifecycle event and
                # phase transition that drives the frontend status display.
                "handlers": ["console", "sse_notifications_file", "app_file"],
                "level": "DEBUG",
                "propagate": False,
            },
            "backend.llm": {
                "handlers": ["console", "llm_file", "app_file"],
                "level": "INFO",
                "propagate": False,
            },
            "backend.resource_api": {
                "handlers": ["console", "resource_api_file", "app_file"],
                "level": "INFO",
                "propagate": False,
            },
            "backend.streaming": {
                "handlers": ["console", "streaming_file", "app_file"],
                "level": "DEBUG",
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
