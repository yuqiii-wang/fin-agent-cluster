"""app.llm — unified LLM client.

Selects the active provider based on the ``LLM_PROVIDER`` setting and
returns a LangChain ``BaseChatModel`` that callers can use uniformly.

Supported providers
-------------------
- ``ark``      — Volcano Engine ARK / Doubao (OpenAI-compatible endpoint)
- ``gemini``   — Google Gemini (OpenAI-compatible endpoint, no extra packages)
- ``ollama`` — Local Ollama (Python binding or Ollama server REST API)

Usage
-----
    from backend.llm import get_llm

    llm = get_llm()                  # provider from LLM_PROVIDER env var
    llm = get_llm(temperature=0.0)   # deterministic output
"""

from backend.llm.factory import get_active_provider, get_llm

__all__ = ["get_active_provider", "get_llm"]
