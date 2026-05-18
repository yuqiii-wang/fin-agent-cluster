"""Ollama chat model provider."""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama

from backend.config import get_settings


def get_ollama_llm() -> BaseChatModel:
    """Return a ChatOllama instance configured from settings."""
    settings = get_settings()
    return ChatOllama(
        model=settings.OLLAMA_LLM_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
    )
