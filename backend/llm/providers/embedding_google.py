"""Google embedding provider implementation."""

from __future__ import annotations

from backend.config import get_settings


def get_google_embedder() -> object:
    """Return configured Google embedding client.

    Returns:
        ``GoogleGenerativeAIEmbeddings`` instance.

    Raises:
        ValueError: If ``GOOGLE_GEMINI_API_KEY`` is missing.
    """
    settings = get_settings()
    if not settings.GOOGLE_GEMINI_API_KEY:
        raise ValueError("GOOGLE_GEMINI_API_KEY must be set for EMBEDDING_PROVIDER=google")

    from langchain_google_genai import GoogleGenerativeAIEmbeddings  # noqa: PLC0415

    return GoogleGenerativeAIEmbeddings(
        model=settings.GOOGLE_EMBEDDING_MODEL,
        google_api_key=settings.GOOGLE_GEMINI_API_KEY,
        task_type="retrieval_document",
    )
