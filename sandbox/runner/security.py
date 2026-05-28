"""Pre-execution security validation — standalone, no external dependencies.

Blocks obvious escape patterns before spawning any subprocess.  The Docker
network is already isolated (internal: true), so these checks are a second
layer of defence that rejects obviously dangerous patterns early and surfaces
a clear error without wasting subprocess startup overhead.

Blocked patterns
----------------
1. Path traversal — ``../`` and ``..\``.
2. Sensitive absolute paths — ``/proc``, ``/sys``, ``/dev``, ``/etc``,
   ``/root``, ``/run``, ``/boot``.
3. Raw socket construction — ``socket.socket``, ``AF_INET``, ``AF_UNIX``.
4. Network-related top-level imports — ``socket``, ``urllib``, ``httpx``,
   ``requests``, ``aiohttp``, ``http.client``.
"""

from __future__ import annotations

import re

_RE_PATH_TRAVERSAL = re.compile(r"\.\.[/\\]")
_RE_SENSITIVE_ABS = re.compile(
    r'["\'/](?:proc|sys|dev|etc|root|run|boot)(?:/|\b)',
    re.IGNORECASE,
)
_RE_RAW_SOCKET = re.compile(
    r"\bsocket\.socket\b|\bAF_INET\b|\bAF_UNIX\b|\bAF_INET6\b"
)
_RE_NETWORK_IMPORT = re.compile(
    r"^\s*(?:import|from)\s+(?:socket|urllib|httpx|requests|aiohttp|"
    r"http\.client|ftplib|smtplib|imaplib|poplib|telnetlib|xmlrpc)\b",
    re.MULTILINE,
)

_RULES: list[tuple[re.Pattern[str], str]] = [
    (_RE_PATH_TRAVERSAL, "path traversal sequences (../) are not allowed"),
    (
        _RE_SENSITIVE_ABS,
        "references to sensitive system paths (/proc, /sys, /dev, /etc, /root) are not allowed",
    ),
    (_RE_RAW_SOCKET, "raw socket construction is not allowed"),
    (_RE_NETWORK_IMPORT, "network-related imports are not allowed"),
]


def validate_script(script: str, *, language: str = "python") -> str | None:
    """Return a violation reason string, or ``None`` if the script is clean.

    Args:
        script:   Source code text to validate.
        language: ``"python"`` or ``"bash"`` (rules currently apply to both).

    Returns:
        Human-readable violation reason, or ``None`` when no rule matched.
    """
    for pattern, reason in _RULES:
        if pattern.search(script):
            return reason
    return None
