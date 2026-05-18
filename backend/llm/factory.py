from typing import Literal

from langchain_core.language_models import BaseChatModel

from backend.llm.providers.mock_llm import get_mock_llm
from backend.llm.providers.ollama import get_ollama_llm

LLMProvider = Literal["mock", "ollama"]


def get_llm(provider: LLMProvider = "mock") -> BaseChatModel:
    """Return the configured LLM instance.

    Args:
        provider: Which LLM backend to use. Defaults to ``"mock"``.
    """
    if provider == "ollama":
        return get_ollama_llm()
    return get_mock_llm()