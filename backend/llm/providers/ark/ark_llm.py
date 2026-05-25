"""ARK (Volcano Engine / Doubao) chat model provider.

ARK exposes an OpenAI-compatible ``/chat/completions`` endpoint at
``https://ark.cn-beijing.volces.com/api/v3``.  We use
``langchain_openai.ChatOpenAI`` pointing at the ARK base URL.

For completion (non-streaming, no thinking) mode:
- ``streaming=False``
- No ``enable_thinking`` extra header
- ``temperature`` near 0 for deterministic structured output

Usage::

    from backend.llm.providers.ark import get_ark_llm

    llm = get_ark_llm()
    result = llm.invoke([HumanMessage(content="Summarise: Apple beat EPS")])
"""

from __future__ import annotations

import logging

from langchain_openai import ChatOpenAI

from backend.config import get_settings

logger = logging.getLogger(__name__)


def get_ark_llm(temperature: float = 0.1) -> ChatOpenAI:
    """Return a :class:`ChatOpenAI` instance configured for ARK.

    Uses the ARK OpenAI-compatible endpoint.  Thinking mode is not enabled
    so the response is a standard completion (no ``<think>`` tokens).

    Args:
        temperature: Sampling temperature; use a low value for structured output.

    Returns:
        :class:`~langchain_openai.ChatOpenAI` bound to ARK.

    Raises:
        ValueError: When ``ARK_API_KEY`` is not configured.
    """
    settings = get_settings()
    if not settings.ARK_API_KEY:
        raise ValueError("ARK_API_KEY is not set; cannot initialise ARK LLM")
    return ChatOpenAI(
        model=settings.ARK_MODEL,
        api_key=settings.ARK_API_KEY,          # type: ignore[arg-type]
        base_url=settings.ARK_BASE_URL,
        temperature=temperature,
        streaming=False,
    )


__all__ = ["get_ark_llm"]
