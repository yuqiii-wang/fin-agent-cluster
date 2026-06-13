import logging
from typing import Literal

from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

from backend.config import get_settings
from _shared.llm.embedding import EmbeddingClient
from _shared.llm.providers.mock_llm import get_mock_llm
from _shared.llm.providers.mock_emb import get_mock_embedder
from _shared.llm.providers.ollama import get_ollama_llm

LLMProvider = Literal["mock", "ollama", "ark"]
EmbeddingProvider = Literal["mock", "google", "ollama"]


def get_llm(
    provider: LLMProvider | None = None,
    streaming: bool = True,
) -> BaseChatModel:
    """Return a chat model for the given provider.

    When ``provider`` is ``None`` the value of ``Settings.LLM_PROVIDER`` is
    used, falling back to ``"mock"``.

    Args:
        provider: Which LLM backend to use.  ``None`` defers to settings.
        streaming: Whether to enable SSE token streaming (ARK only at
            construction time).  Set ``False`` for structured-output / completion
            calls that use ``.invoke()``; Ollama and Mock handle this per-call
            via ``_generate`` / ``_astream`` regardless of this flag.

    Returns:
        :class:`~langchain_core.language_models.BaseChatModel`
    """
    settings = get_settings()
    resolved = (provider or settings.LLM_PROVIDER or "mock").strip().lower()

    if resolved == "ollama":
        return get_ollama_llm()
    if resolved == "ark":
        from _shared.llm.providers.ark import get_ark_llm
        return get_ark_llm(temperature=0.1, streaming=streaming)
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
            from _shared.llm.providers.google_emb import get_google_embedder
            return get_google_embedder()
    if resolved == "ollama":
        from _shared.llm.providers.ollama_emb import get_ollama_embedder
        return get_ollama_embedder()
    return get_mock_embedder()
