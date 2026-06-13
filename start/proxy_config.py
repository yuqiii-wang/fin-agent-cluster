"""Outbound proxy configuration for run.py."""
import os
import socket
from urllib.parse import urlparse

_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def configure_proxy(proxy: str | None) -> None:
    """Inject outbound proxy into os.environ so every HTTP library picks it up.

    Covers: httpx (trust_env=True default), requests (yfinance/DDGS), openai SDK,
    google-generativeai, and any other env-aware HTTP client.
    Sets NO_PROXY to exclude localhost so DB and local health checks are unaffected.

    Args:
        proxy: Proxy URL (e.g. ``'http://127.0.0.1:7890'``) or ``None`` to skip.
    """
    if proxy:
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
