"""Google Gemini LLM provider.

Uses the Gemini OpenAI-compatible REST endpoint so that no additional
packages beyond ``langchain-openai`` are required.

Compatible endpoint reference:
  https://ai.google.dev/gemini-api/docs/openai
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from backend.config import get_settings

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def get_gemini_llm(temperature: float = 0.3) -> ChatOpenAI:
    """Return a ChatOpenAI instance pointed at Gemini's OpenAI-compat endpoint.

    Proxy is picked up automatically from ``HTTPS_PROXY``/``HTTP_PROXY`` env
    vars injected at startup via ``run.py``.

    Args:
        temperature: Sampling temperature passed to the model.

    Returns:
        Configured :class:`~langchain_openai.ChatOpenAI` instance.

    Raises:
        ValueError: If ``GOOGLE_GEMINI_API_KEY`` is not set.
    """
    s = get_settings()
    if not s.GOOGLE_GEMINI_API_KEY:
        raise ValueError("GOOGLE_GEMINI_API_KEY must be set for LLM_PROVIDER='gemini'")
    return ChatOpenAI(
        api_key=s.GOOGLE_GEMINI_API_KEY,
        base_url=_GEMINI_BASE_URL,
        model=s.GOOGLE_GEMINI_MODEL,
        temperature=temperature,
    )
