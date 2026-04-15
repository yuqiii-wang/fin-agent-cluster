"""Local Ollama LLM provider.

Connects to a running Ollama server which exposes an API for local models.
Configure `OLLAMA_SERVER_URL` (default `http://127.0.0.1:11434`) and
`OLLAMA_MODEL` (default `qwen3.5-27b`).
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

import httpx
from langchain_openai import ChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel

from backend.config import get_settings


def _build_openai_base_url(server_url: str) -> str:
    """Return Ollama's OpenAI-compatible base URL."""
    normalized = server_url.rstrip("/")
    if normalized.endswith("/v1"):
        return normalized
    return f"{normalized}/v1"


def _should_bypass_proxy(base_url: str) -> bool:
    """Return True when target host is local and should bypass env proxy."""
    host = (urlparse(base_url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def probe_ollama(timeout: float = 10.0) -> bool:
    """Return True if the Ollama server is reachable and can generate a response.

     Performs two checks:
     1. ``/api/tags`` — server alive.
     2. ``/api/chat`` — model actually loaded and inference works in streaming
         mode (expects at least one non-empty token for prompt ``"ok"``).

    Uses a direct connection (no proxy) since Ollama is always local.

    Args:
        timeout: HTTP timeout in seconds for each request.

    Returns:
        ``True`` when the server responds and the model generates output.
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)

    s = get_settings()
    base = s.OLLAMA_SERVER_URL.rstrip("/")

    try:
        with httpx.Client(trust_env=False, timeout=timeout) as client:
            # Step 1: server alive
            tags_resp = client.get(f"{base}/api/tags")
            if tags_resp.status_code >= 500:
                return False

            # Step 2: model chat response in streaming mode
            chat_resp = client.post(
                f"{base}/api/chat",
                json={
                    "model": s.OLLAMA_MODEL,
                    "messages": [{"role": "user", "content": "ok"}],
                    "stream": True,
                    "options": {"num_predict": 1},
                },
            )
            if chat_resp.status_code >= 400:
                _log.debug(
                    "[ollama.probe] chat returned %s: %s",
                    chat_resp.status_code,
                    chat_resp.text[:200],
                )
                return False

            for line in chat_resp.iter_lines():
                if not line:
                    continue
                payload = json.loads(line)
                token = ((payload.get("message") or {}).get("content") or "").strip()
                if token:
                    return True
            return False
    except Exception as exc:
        _log.debug("[ollama.probe] unreachable: %s", exc)
        return False


def get_ollama_llm(temperature: float = 0.3) -> BaseChatModel:
    """Return a chat model backed by a local Ollama server.

    Args:
        temperature: Sampling temperature passed to the model.

    Returns:
        A :class:`~langchain_core.language_models.chat_models.BaseChatModel`
        instance (``ChatOpenAI`` configured for Ollama).
    """
    s = get_settings()

    base_url = _build_openai_base_url(s.OLLAMA_SERVER_URL)
    bypass_proxy = _should_bypass_proxy(base_url)
    http_client = httpx.Client(trust_env=not bypass_proxy)

    return ChatOpenAI(
        api_key="ollama",  # Ollama doesn't require a strict auth key
        base_url=base_url,
        model=s.OLLAMA_MODEL,
        temperature=temperature,
        streaming=True,
        http_client=http_client,
    )
