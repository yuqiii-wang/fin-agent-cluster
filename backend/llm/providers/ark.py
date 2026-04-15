"""Volcano Engine ARK / Doubao LLM provider.

Uses the OpenAI-compatible endpoint exposed by Volcano Engine's ARK service.
Requires ARK_API_KEY, ARK_BASE_URL, and ARK_MODEL in settings.
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from backend.config import get_settings


def get_ark_llm(temperature: float = 0.3) -> ChatOpenAI:
    """Return a ChatOpenAI instance pointed at the ARK/Doubao endpoint.

    Proxy is picked up automatically from ``HTTPS_PROXY``/``HTTP_PROXY`` env
    vars injected at startup via ``run.py``.

    Args:
        temperature: Sampling temperature passed to the model.

    Returns:
        Configured :class:`~langchain_openai.ChatOpenAI` instance.

    Raises:
        ValueError: If ``ARK_API_KEY`` is not set.
    """
    s = get_settings()
    if not s.ARK_API_KEY:
        raise ValueError("ARK_API_KEY must be set for LLM_PROVIDER='ark'")
    return ChatOpenAI(
        api_key=s.ARK_API_KEY,
        base_url=s.ARK_BASE_URL,
        model=s.ARK_MODEL,
        temperature=temperature,
    )
