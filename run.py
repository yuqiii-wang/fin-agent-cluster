"""Run the FastAPI server with proper Windows asyncio configuration."""
import asyncio
import os
import sys
import uvicorn
from backend.config import get_settings


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


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run the FastAPI server.")
    parser.add_argument("--no-proxy", action="store_true", help="Disable the use of the proxy even if configured.")
    args = parser.parse_args()

    settings = get_settings()
    proxy_to_use = None if args.no_proxy else settings.HTTP_PROXY
    _configure_proxy(proxy_to_use)

    if sys.platform == "win32":
        # psycopg requires SelectorEventLoop; Windows defaults to ProactorEventLoop.
        # Setting the policy here propagates to all uvicorn worker processes.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",  # Loopback only — Kong (host.docker.internal) still reaches it; external clients cannot bypass Kong.
        port=settings.FASTAPI_PORT,
        reload=True,
        reload_dirs=["backend"],
        workers=1,
    )
