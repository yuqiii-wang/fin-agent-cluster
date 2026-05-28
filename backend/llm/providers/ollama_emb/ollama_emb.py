"""Ollama embedding provider.

Calls the Ollama ``/api/embed`` REST endpoint to generate embeddings
from a locally-running Ollama instance.

The model is configured via ``Settings.OLLAMA_EMBED_MODEL``
(default ``"qwen3-0.6b-emb"``).

Usage::

    from backend.llm.providers.ollama_emb import get_ollama_embedder

    embedder = get_ollama_embedder()
    vecs = embedder.embed_documents(["Apple beat earnings"])
"""

from __future__ import annotations

import logging

from backend.config import get_settings
from backend.httpx_client import HTTPError, make_ollama_sync_client

logger = logging.getLogger(__name__)

_BATCH_SIZE = 64  # Ollama handles multiple inputs per request


class OllamaEmbeddingClient:
    """Synchronous Ollama embedding client using the ``/api/embed`` endpoint.

    Satisfies the :class:`~backend.llm.embedding.EmbeddingClient` protocol.

    Attributes:
        model:    Ollama model name, e.g. ``"qwen3-0.6b-emb"``.
        base_url: Ollama server base URL.
    """

    def __init__(self, model: str, base_url: str) -> None:
        """Initialise the client.

        Args:
            model:    Ollama embedding model name.
            base_url: Ollama base URL, e.g. ``"http://localhost:11434"``.
        """
        self.model = model
        self.base_url = base_url.rstrip("/")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts via the Ollama ``/api/embed`` endpoint.

        Texts are sent in batches of :data:`_BATCH_SIZE` to stay within
        Ollama's recommended per-request limit.

        Args:
            texts: Plain-text strings to embed.

        Returns:
            List of float vectors.

        Raises:
            RuntimeError: On HTTP error or unexpected response shape.
        """
        if not texts:
            return []

        results: list[list[float]] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            try:
                with make_ollama_sync_client(self.base_url, timeout_seconds=60.0) as client:
                    resp = client.post(
                        f"{self.base_url}/api/embed",
                        json={"model": self.model, "input": batch},
                    )
                    resp.raise_for_status()
            except HTTPError as exc:
                logger.error("ollama_emb.embed_documents HTTP error batch_start=%d error=%s", i, exc)
                raise RuntimeError(f"ollama_emb.embed_documents HTTP error: {exc}") from exc

            data = resp.json()
            embeddings: list | None = data.get("embeddings")
            if not embeddings:
                raise RuntimeError(
                    f"ollama_emb.embed_documents unexpected response shape: {data!r}"
                )
            results.extend(embeddings)

        return results


def get_ollama_embedder() -> OllamaEmbeddingClient:
    """Construct an :class:`OllamaEmbeddingClient` from application settings.

    Returns:
        Configured :class:`OllamaEmbeddingClient` instance.
    """
    settings = get_settings()
    return OllamaEmbeddingClient(
        model=settings.OLLAMA_EMBED_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
    )


__all__ = ["OllamaEmbeddingClient", "get_ollama_embedder"]
