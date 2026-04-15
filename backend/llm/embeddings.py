"""Embedding provider factory with runtime override support.

This module resolves the active embedding provider and exposes a unified
``embed_documents`` interface for callers. Concrete implementations are
provided in ``backend.llm.providers`` modules.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional, Protocol

from backend.config import get_settings

logger = logging.getLogger(__name__)

_SUPPORTED_EMBED_PROVIDERS = ("google", "ollama")
_runtime_embedding_provider_override: Optional[str] = None


class EmbeddingClient(Protocol):
    """Minimal embedding interface used by downstream transformers."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents into dense vectors."""


def set_embedding_provider_override(provider: str) -> None:
    """Override EMBEDDING_PROVIDER at runtime and clear the embedder cache."""
    global _runtime_embedding_provider_override
    normalized = provider.lower().strip()
    if normalized not in _SUPPORTED_EMBED_PROVIDERS:
        raise ValueError(
            f"Unknown embedding provider={provider!r}. "
            f"Supported values: {', '.join(_SUPPORTED_EMBED_PROVIDERS)}"
        )
    _runtime_embedding_provider_override = normalized
    get_embedder.cache_clear()
    logger.info("[embeddings] runtime provider override -> %s", normalized)


def get_active_embedding_provider() -> str:
    """Return active embedding provider including runtime override."""
    return (_runtime_embedding_provider_override or get_settings().EMBEDDING_PROVIDER).lower().strip()


def probe_ollama_embedding(timeout: float = 10.0) -> bool:
    """Delegate Ollama embedding health check to provider module."""
    from backend.llm.providers.embedding_ollama import probe_ollama_embedding as _probe  # noqa: PLC0415

    return _probe(timeout=timeout)


def _build_embedder(provider: str) -> EmbeddingClient:
    """Build concrete embedding client from provider modules."""
    settings = get_settings()

    if provider == "ollama":
        from backend.llm.providers.embedding_ollama import OllamaEmbeddingClient  # noqa: PLC0415

        return OllamaEmbeddingClient(
            base_url=settings.OLLAMA_SERVER_URL,
            model=settings.OLLAMA_EMBED_MODEL,
        )

    if provider == "google":
        from backend.llm.providers.embedding_google import get_google_embedder  # noqa: PLC0415

        return get_google_embedder()  # type: ignore[return-value]

    raise ValueError(
        f"Unknown EMBEDDING_PROVIDER={provider!r}. "
        f"Supported values: {', '.join(_SUPPORTED_EMBED_PROVIDERS)}"
    )


@lru_cache(maxsize=1)
def get_embedder() -> EmbeddingClient:
    """Return the configured embedding client with optional runtime override."""
    provider = get_active_embedding_provider()
    return _build_embedder(provider)
