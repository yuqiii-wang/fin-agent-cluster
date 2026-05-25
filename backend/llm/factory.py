import logging
from typing import Literal

from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

from backend.config import get_settings
from backend.llm.embedding import EmbeddingClient
from backend.llm.providers.mock_llm import get_mock_llm
from backend.llm.providers.mock_emb import get_mock_embedder
from backend.llm.providers.ollama import get_ollama_llm

LLMProvider = Literal["mock", "ollama", "ark"]
EmbeddingProvider = Literal["mock", "google", "ollama"]


def get_llm(provider: LLMProvider = "mock") -> BaseChatModel:
    """Return the configured streaming LLM instance.

    Args:
        provider: Which LLM backend to use. Defaults to ``"mock"``.
    """
    if provider == "ollama":
        return get_ollama_llm()
    if provider == "ark":
        from backend.llm.providers.ark import get_ark_llm
        return get_ark_llm()
    return get_mock_llm()


def get_completion_llm(provider: LLMProvider | None = None) -> BaseChatModel:
    """Return a non-streaming completion LLM for structured output tasks.

    Thinking / chain-of-thought is disabled; response is a single completion.
    Provider defaults to ``Settings.LLM_PROVIDER``.

    Args:
        provider: Override the provider; falls back to settings when ``None``.

    Returns:
        :class:`~langchain_core.language_models.BaseChatModel` in completion mode.
    """
    settings = get_settings()
    resolved = (provider or settings.LLM_PROVIDER or "mock").strip().lower()

    if resolved == "ark":
        from backend.llm.providers.ark import get_ark_llm
        return get_ark_llm(temperature=0.1)
    if resolved == "ollama":
        return get_ollama_llm()
    return get_mock_llm()


def get_embedder(provider: EmbeddingProvider | None = None) -> EmbeddingClient:
    """Return the configured embedding client.

    Provider defaults to ``Settings.EMBEDDING_PROVIDER``.

    Args:
        provider: Override the provider; falls back to settings when ``None``.

    Returns:
        An object satisfying the :class:`~backend.llm.embedding.EmbeddingClient` protocol.
    """
    settings = get_settings()
    resolved = (provider or settings.EMBEDDING_PROVIDER or "mock").strip().lower()

    if resolved == "google":
        if not settings.GOOGLE_GEMINI_API_KEY:
            logger.error(
                "get_embedder: GOOGLE_GEMINI_API_KEY is not set; falling back to ollama embedder"
            )
            resolved = "ollama"
        else:
            from backend.llm.providers.google_emb import get_google_embedder
            return get_google_embedder()
    if resolved == "ollama":
        from backend.llm.providers.ollama_emb import get_ollama_embedder
        return get_ollama_embedder()
    return get_mock_embedder()
