"""Pre-execution security validation for sandbox scripts.

The primary isolation relies on OS-level mechanisms: Linux network namespaces
(``unshare --net``), resource limits (``setrlimit``), and a confined CWD.
These checks are a second layer of defence that rejects obviously dangerous
patterns *before* any subprocess is spawned, giving a clearer error message
and avoiding unnecessary process startup overhead.

Blocked patterns
----------------
1. **Path traversal** -- ``../`` and ``..\\`` sequences that could reach outside
   the sandbox working directory.
2. **Sensitive absolute paths** -- references to ``/proc``, ``/sys``, ``/dev``,
   ``/etc``, ``/root``, ``/run``, ``/boot``.
3. **Raw socket construction** -- ``socket.socket``, ``AF_INET``, ``AF_UNIX``
   (belt-and-suspenders; the network namespace already blocks all I/O).
4. **Network-related top-level imports** -- ``socket``, ``urllib``, ``httpx``,
   ``requests``, ``aiohttp``, ``http.client``.  Internal Python stdlib helpers
   (``json``, ``csv``, ``pathlib``, etc.) are intentionally not blocked.
"""

from __future__ import annotations

import re

from backend.sandbox.errors import SandboxSecurityError
from backend.sandbox.errors.codes import SANDBOX_SECURITY_VIOLATION

__all__ = ["validate_script"]


# ── Compiled rules ─────────────────────────────────────────────────────────────

# ``../`` or ``..\\`` -- directory traversal
_RE_PATH_TRAVERSAL = re.compile(r"\.\.[/\\]")

# Sensitive absolute Linux paths that must not be accessed
_RE_SENSITIVE_ABS = re.compile(
    r'["\'/](?:proc|sys|dev|etc|root|run|boot)(?:/|\b)',
    re.IGNORECASE,
)

# Direct socket type construction (belt-and-suspenders; net-ns already blocks)
_RE_RAW_SOCKET = re.compile(r"\bsocket\.socket\b|\bAF_INET\b|\bAF_UNIX\b|\bAF_INET6\b")

# Network-related top-level Python imports
_RE_NETWORK_IMPORT = re.compile(
    r"^\s*(?:import|from)\s+(?:socket|urllib|httpx|requests|aiohttp|http\.client|ftplib|smtplib|imaplib|poplib|telnetlib|xmlrpc)\b",
    re.MULTILINE,
)

_RULES: list[tuple[re.Pattern[str], str]] = [
    (_RE_PATH_TRAVERSAL, "path traversal sequences (../) are not allowed"),
    (_RE_SENSITIVE_ABS, "references to sensitive system paths (/proc, /sys, /dev, /etc, /root) are not allowed"),
    (_RE_RAW_SOCKET, "raw socket construction is not allowed"),
    (_RE_NETWORK_IMPORT, "network-related imports are not allowed"),
]


def validate_script(script: str, *, language: str = "python") -> None:
    """Check *script* for blocked patterns before spawning a subprocess.

    Args:
        script:   Source code text to validate.
        language: ``"python"`` or ``"bash"`` (reserved for language-specific
                  future rules; the current rules apply to both).

    Raises:
        SandboxSecurityError: When any blocked pattern is detected.
            The exception message includes the error code and the specific
            rule that was violated.
    """
    for pattern, reason in _RULES:
        if pattern.search(script):
            raise SandboxSecurityError(
                f"[{SANDBOX_SECURITY_VIOLATION}] Script rejected -- {reason}."
            )
