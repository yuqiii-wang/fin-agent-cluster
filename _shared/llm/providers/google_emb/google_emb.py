"""Google Generative AI embedding provider.

Uses the ``google-genai`` SDK (``google.genai``) to call Google's
``text-embedding-004`` model (or the model configured in
:class:`~backend.config.Settings`).

Dimensionality is controlled by ``Settings.GOOGLE_EMBEDDING_DIMENSIONS``
(default 768).  The Google API supports output dimensions from 1 to 768
for ``text-embedding-004``.

Usage::

    from _shared.llm.providers.google_emb import get_google_embedder

    embedder = get_google_embedder()
    vecs = embedder.embed_documents(["Apple beat earnings", "Fed cuts rates"])
"""

from __future__ import annotations

import logging

from google import genai
from google.genai import types

from backend.config import get_settings

logger = logging.getLogger(__name__)


class GoogleEmbeddingClient:
    """Synchronous Google text-embedding client using the google-genai SDK.

    Satisfies the :class:`~backend.llm.embedding.EmbeddingClient` protocol.

    Attributes:
        model:      Model name, e.g. ``"models/text-embedding-004"``.
        dimensions: Output vector length (up to 768 for text-embedding-004).
    """

    def __init__(self, model: str, api_key: str, dimensions: int) -> None:
        """Initialise the client.

        Args:
            model:      Google embedding model identifier.
            api_key:    Google API key.
            dimensions: Number of output dimensions (1–768).
        """
        self._client = genai.Client(api_key=api_key)
        self.model = model
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts via the Google Generative AI API.

        Calls are batched in groups of 100 (Google's recommended maximum)
        to avoid request-size limits.

        Args:
            texts: Plain-text strings to embed.

        Returns:
            List of float vectors, each of length ``self.dimensions``.

        Raises:
            RuntimeError: If the Google API returns an unexpected response shape.
        """
        if not texts:
            return []

        results: list[list[float]] = []
        batch_size = 100
        embed_config = types.EmbedContentConfig(
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=self.dimensions,
        )

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            try:
                response = self._client.models.embed_content(
                    model=self.model,
                    contents=batch,
                    config=embed_config,
                )
            except Exception as exc:
                logger.error("google_emb.embed_documents failed batch_start=%d error=%s", i, exc)
                raise RuntimeError(f"google_emb.embed_documents error: {exc}") from exc

            if not response.embeddings:
                raise RuntimeError(
                    f"google_emb.embed_documents unexpected response shape: {response!r}"
                )
            results.extend([list(e.values) for e in response.embeddings])

        return results


def get_google_embedder() -> GoogleEmbeddingClient:
    """Construct a :class:`GoogleEmbeddingClient` from application settings.

    Returns:
        Configured :class:`GoogleEmbeddingClient` instance.

    Raises:
        ValueError: When ``GOOGLE_GEMINI_API_KEY`` is not set in settings.
    """
    settings = get_settings()
    if not settings.GOOGLE_GEMINI_API_KEY:
        raise ValueError("GOOGLE_GEMINI_API_KEY is not set; cannot initialise Google embedder")
    return GoogleEmbeddingClient(
        model=settings.GOOGLE_EMBEDDING_MODEL,
        api_key=settings.GOOGLE_GEMINI_API_KEY,
        dimensions=settings.GOOGLE_EMBEDDING_DIMENSIONS,
    )


__all__ = ["GoogleEmbeddingClient", "get_google_embedder"]
