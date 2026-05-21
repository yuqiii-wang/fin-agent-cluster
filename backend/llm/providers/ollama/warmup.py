"""Ollama model warmup — sends a minimal request to preload model weights into GPU memory."""

from __future__ import annotations

import logging
import urllib.parse

import httpx

logger = logging.getLogger(__name__)

# Hostnames that should never be routed through a proxy.
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def warmup_ollama() -> None:
    """Send a minimal chat request to Ollama to load model weights into GPU memory.

    Called once at startup (before uvicorn instances begin accepting traffic)
    so the first real streaming request does not incur the cold-start latency
    of loading model weights into VRAM.

    The request is synchronous and intentionally blocks run.py's main thread
    so Ollama is guaranteed to be loaded before the first client connection
    arrives.  Errors are logged and swallowed — a warmup failure must never
    prevent process startup.
    """
    from backend.config import get_settings

    settings = get_settings()
    base_url: str = settings.OLLAMA_BASE_URL
    model: str = settings.OLLAMA_LLM_MODEL
    num_gpu: int = settings.OLLAMA_NUM_GPU

    url = f"{base_url}/api/chat"

    # Resolve proxy: skip for loopback destinations (Ollama running locally).
    proxy: str | None = None
    if settings.HTTP_PROXY:
        host = urllib.parse.urlparse(base_url).hostname or ""
        if host not in _LOOPBACK_HOSTS:
            proxy = settings.HTTP_PROXY

    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": False,
        "options": {"num_gpu": num_gpu},
    }

    print(f"[ollama_warmup] warming up model={model} at {base_url} …")
    try:
        with httpx.Client(proxy=proxy, timeout=httpx.Timeout(120.0)) as client:
            resp = client.post(url, json=body)
            if resp.status_code >= 400:
                logger.error(
                    "[ollama_warmup] warmup HTTP %d from %s: %s",
                    resp.status_code, url, resp.text[:200],
                )
                return
        print(f"[ollama_warmup] model={model} loaded and ready")
    except httpx.ConnectError as exc:
        logger.error("[ollama_warmup] cannot connect to Ollama at %s (non-fatal): %s", url, exc)
    except httpx.TimeoutException as exc:
        logger.error("[ollama_warmup] warmup request timed out at %s (non-fatal): %s", url, exc)
    except Exception as exc:  # noqa: BLE001
        logger.error("[ollama_warmup] warmup failed (non-fatal): %s", exc)


__all__ = ["warmup_ollama"]
