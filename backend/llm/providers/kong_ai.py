"""Kong AI Gateway LLM provider.

Routes LLM chat calls through Kong's ``ai-proxy`` plugin, which exposes an
OpenAI-compatible ``/llm/v1/chat/completions`` endpoint.  Kong centrally
manages model selection, API-key injection, rate limiting, and provider
failover — the FastAPI app only needs to know the Kong proxy URL.

Configure ``KONG_AI_PROXY_URL`` (e.g. ``http://localhost:8000/llm``) and set
``LLM_PROVIDER=kong_ai`` in ``.env`` to activate this provider.
"""

from __future__ import annotations

import logging

import httpx
from langchain_openai import ChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel

from backend.config import get_settings

logger = logging.getLogger(__name__)


def probe_kong_ai(timeout: float = 5.0) -> bool:
    """Return ``True`` when Kong's AI proxy endpoint is reachable.

    Sends a minimal ``/v1/models`` request to Kong's AI proxy.  Kong returns
    a 200 (or 404 — indicating it is up but no models endpoint exists) when
    the proxy is live.

    Args:
        timeout: HTTP timeout in seconds.

    Returns:
        ``True`` when Kong responds with any non-5xx status.
    """
    s = get_settings()
    base = s.KONG_AI_PROXY_URL.rstrip("/")
    try:
        with httpx.Client(trust_env=False, timeout=timeout) as client:
            resp = client.get(f"{base}/v1/models")
            return resp.status_code < 500
    except Exception as exc:
        logger.debug("[kong_ai.probe] Kong AI proxy unreachable: %s", exc)
        return False


def get_kong_ai_llm(temperature: float = 0.3) -> BaseChatModel:
    """Return a LangChain ``ChatOpenAI`` instance pointing at Kong's AI proxy.

    Kong's ``ai-proxy`` plugin exposes an OpenAI-compatible endpoint so
    ``ChatOpenAI`` works without modification.  The model name is whatever
    Kong routes to — typically ``OLLAMA_MODEL`` configured in kong.yml.
    Kong holds the upstream API keys; this client sends none.

    Args:
        temperature: Sampling temperature forwarded to the model.

    Returns:
        A configured ``ChatOpenAI`` instance.

    Raises:
        ValueError: If ``KONG_AI_PROXY_URL`` is not configured.
    """
    s = get_settings()
    if not s.KONG_AI_PROXY_URL:
        raise ValueError(
            "KONG_AI_PROXY_URL is not set — configure it in .env to use LLM_PROVIDER=kong_ai"
        )

    base_url = s.KONG_AI_PROXY_URL.rstrip("/") + "/v1"

    return ChatOpenAI(
        base_url=base_url,
        # Kong ai-proxy does not require a client API key; pass a placeholder
        # so the OpenAI SDK does not raise a missing-key error.
        api_key="kong-managed",  # noqa: S106 — not a real secret
        model=s.OLLAMA_MODEL,  # Kong routes to the model configured in kong.yml
        temperature=temperature,
        # Use direct connection — Kong is local; do not route through outbound proxy.
        http_client=httpx.Client(trust_env=False),
        http_async_client=httpx.AsyncClient(trust_env=False),
    )
