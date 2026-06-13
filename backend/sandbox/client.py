"""HTTP client for the sharded sandbox runner service.

Shard routing
-------------
Thread-ID-based routing mirrors the pattern used for Centrifugo and Redis::

    shard_index = SHA-256(thread_id) % len(nodes)

This ensures every task within the same LangGraph thread consistently targets
the same container so that files written by one task can be read by the next.

Error mapping
-------------
HTTP 422 from runner    -> ``SandboxSecurityError`` or ``SandboxUnsupportedLanguageError``
HTTP connect failure    -> ``SandboxRunnerError``
HTTP timeout            -> ``SandboxTimeoutError``
``timed_out=True`` body -> ``SandboxTimeoutError``
Other HTTP error        -> ``SandboxRunnerError``
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import httpx

from backend.sandbox.errors import (
    SandboxRunnerError,
    SandboxSecurityError,
    SandboxTimeoutError,
    SandboxUnsupportedLanguageError,
)
from backend.sandbox.errors.codes import (
    SANDBOX_RUNNER_ERROR,
    SANDBOX_SECURITY_VIOLATION,
    SANDBOX_TIMEOUT,
    SANDBOX_UNSUPPORTED_LANGUAGE,
)

__all__ = ["execute_in_runner", "start_runner_session", "end_runner_session"]

_LOG = logging.getLogger(__name__)

# Separate timeouts so session lifecycle calls fail fast while execution calls
# wait up to the full runner timeout.
_CONNECT_TIMEOUT_S: float = 5.0
_SESSION_TIMEOUT_S: float = 10.0


# ── Shard routing ─────────────────────────────────────────────────────────────


def _runner_url(thread_id: str, nodes: list[str]) -> str:
    """Return the base URL of the runner shard responsible for *thread_id*.

    Args:
        thread_id: LangGraph thread UUID used as the sharding key.
        nodes:     Ordered list of runner base URLs from config.

    Returns:
        Base URL string, e.g. ``"http://127.0.0.1:8771"``.

    Raises:
        SandboxRunnerError: If *nodes* is empty.
    """
    if not nodes:
        raise SandboxRunnerError(
            f"[{SANDBOX_RUNNER_ERROR}] SANDBOX_RUNNER_NODES is empty; "
            "no sandbox runner is configured."
        )
    idx = int(hashlib.sha256(thread_id.encode()).hexdigest(), 16) % len(nodes)
    return nodes[idx]


# ── Public API ─────────────────────────────────────────────────────────────────


async def execute_in_runner(
    thread_id: str,
    node_id: str,
    script: str,
    language: str,
    stdin: str,
    nodes: list[str],
    timeout: int,
) -> dict[str, Any]:
    """POST ``/execute`` on the correct runner shard and return the result dict.

    Args:
        thread_id: LangGraph thread UUID (used for shard routing).
        node_id:   Agent node execution UUID (workdir key inside the container).
        script:    Source code to execute.
        language:  ``"python"`` or ``"bash"``.
        stdin:     Text piped to the script's stdin.
        nodes:     Ordered list of runner base URLs.
        timeout:   HTTP *read* timeout in seconds (should exceed the runner's
                   internal ``SANDBOX_TIMEOUT_SECONDS`` to account for startup).

    Returns:
        ``{stdout, stderr, exit_code, timed_out}`` dict.

    Raises:
        SandboxSecurityError:            Runner rejected the script (HTTP 422).
        SandboxUnsupportedLanguageError: Unsupported language (HTTP 422).
        SandboxTimeoutError:             HTTP-level timeout or ``timed_out=True`` body.
        SandboxRunnerError:              HTTP transport or connectivity error.
    """
    url = _runner_url(thread_id, nodes)
    payload: dict[str, Any] = {
        "script": script,
        "language": language,
        "stdin": stdin,
        "node_id": node_id,
    }

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=_CONNECT_TIMEOUT_S,
                read=float(timeout),
                write=10.0,
                pool=5.0,
            )
        ) as client:
            resp = await client.post(f"{url}/execute", json=payload)
    except httpx.ConnectError as exc:
        raise SandboxRunnerError(
            f"[{SANDBOX_RUNNER_ERROR}] Cannot connect to sandbox runner at {url}: {exc}"
        ) from exc
    except httpx.TimeoutException as exc:
        raise SandboxTimeoutError(
            f"[{SANDBOX_TIMEOUT}] HTTP timeout waiting for sandbox runner at {url}."
        ) from exc
    except httpx.HTTPError as exc:
        raise SandboxRunnerError(
            f"[{SANDBOX_RUNNER_ERROR}] HTTP error from sandbox runner at {url}: {exc}"
        ) from exc

    if resp.status_code == 422:
        detail: str = resp.json().get("detail", "")
        if "rejected" in detail.lower() or "not allowed" in detail.lower():
            raise SandboxSecurityError(
                f"[{SANDBOX_SECURITY_VIOLATION}] {detail}"
            )
        raise SandboxUnsupportedLanguageError(
            f"[{SANDBOX_UNSUPPORTED_LANGUAGE}] {detail}"
        )

    if not resp.is_success:
        raise SandboxRunnerError(
            f"[{SANDBOX_RUNNER_ERROR}] Runner returned HTTP {resp.status_code}: "
            f"{resp.text[:200]}"
        )

    return resp.json()


async def start_runner_session(
    thread_id: str,
    node_id: str,
    nodes: list[str],
) -> None:
    """POST ``/session/{node_id}`` on the correct runner shard.

    Args:
        thread_id: LangGraph thread UUID (shard routing key).
        node_id:   Agent node execution UUID.
        nodes:     Ordered list of runner base URLs.

    Raises:
        SandboxRunnerError: If the HTTP call fails.
    """
    url = _runner_url(thread_id, nodes)
    try:
        async with httpx.AsyncClient(timeout=_SESSION_TIMEOUT_S) as client:
            resp = await client.post(f"{url}/session/{node_id}")
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise SandboxRunnerError(
            f"[{SANDBOX_RUNNER_ERROR}] Cannot start sandbox session "
            f"for node {node_id!r} on {url}: {exc}"
        ) from exc


async def end_runner_session(
    thread_id: str,
    node_id: str,
    nodes: list[str],
) -> None:
    """DELETE ``/session/{node_id}`` on the correct runner shard.

    Errors are logged and suppressed so a cleanup failure never masks the
    underlying exception from ``build_agent``.

    Args:
        thread_id: LangGraph thread UUID (shard routing key).
        node_id:   Agent node execution UUID.
        nodes:     Ordered list of runner base URLs.
    """
    url = _runner_url(thread_id, nodes)
    try:
        async with httpx.AsyncClient(timeout=_SESSION_TIMEOUT_S) as client:
            resp = await client.delete(f"{url}/session/{node_id}")
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        _LOG.error(
            "[%s] Failed to end sandbox session for node %r on %s: %s",
            SANDBOX_RUNNER_ERROR,
            node_id,
            url,
            exc,
        )
