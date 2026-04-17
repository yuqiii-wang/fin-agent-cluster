"""LLM factory — resolves the active provider from settings and returns a chat model.

The returned instance is cached per (provider, temperature) pair so repeated
calls share the same underlying connection pool.

Failover: the primary provider (set via ``LLM_PROVIDER``) is wrapped with
``with_fallbacks()`` so that any runtime error automatically retries on the
next available provider in the order: ark → gemini.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

from langchain_core.language_models.chat_models import BaseChatModel

from backend.config import get_settings

logger = logging.getLogger(__name__)

_SUPPORTED_PROVIDERS = ("ark", "gemini", "ollama", "kong_ai")
# Providers eligible for automatic failover (excludes ollama/kong_ai which need local setup)
_FAILOVER_CANDIDATES = ("ark", "gemini")

# Set at runtime by startup probe; takes precedence over LLM_PROVIDER in settings.
_runtime_provider_override: Optional[str] = None


def set_provider_override(provider: str) -> None:
    """Override LLM_PROVIDER at runtime and clear the model cache.

    Called by the startup probe when a preferred provider (e.g. Ollama) is
    confirmed reachable, so subsequent :func:`get_llm` calls use it.
    """
    global _runtime_provider_override
    _runtime_provider_override = provider
    get_llm.cache_clear()
    logger.info("[llm.factory] runtime provider override → %s", provider)


def get_active_provider() -> str:
    """Return the currently active LLM provider name.

    Reflects any runtime override set by :func:`set_provider_override` first,
    falling back to the ``LLM_PROVIDER`` setting from ``.env``.

    Returns:
        Lower-cased provider name (e.g. ``"ollama"``, ``"ark"``, ``"gemini"``).
    """
    return (_runtime_provider_override or get_settings().LLM_PROVIDER).lower().strip()


def _build_provider(provider: str, temperature: float) -> Optional[BaseChatModel]:
    """Instantiate a provider, returning ``None`` if it is not configured.

    Args:
        provider:    Provider name (``'ark'``, ``'gemini'``, or ``'ollama'``).
        temperature: Sampling temperature.

    Returns:
        A configured chat model, or ``None`` when required keys are absent.
    """
    try:
        if provider == "ark":
            from backend.llm.providers.ark import get_ark_llm
            return get_ark_llm(temperature)
        if provider == "gemini":
            from backend.llm.providers.gemini import get_gemini_llm
            return get_gemini_llm(temperature)
        if provider == "ollama":
            from backend.llm.providers.ollama import get_ollama_llm
            return get_ollama_llm(temperature)
        if provider == "kong_ai":
            from backend.llm.providers.kong_ai import get_kong_ai_llm
            return get_kong_ai_llm(temperature)
    except ValueError as exc:
        logger.debug("[llm.factory] provider %r unavailable: %s", provider, exc)
    return None


@lru_cache(maxsize=8)
def get_llm(temperature: float = 0.3) -> BaseChatModel:
    """Return the configured LLM chat model, with automatic failover.

    The primary provider is set via ``LLM_PROVIDER`` (default: ``ark``).
    If other providers in ``_FAILOVER_CANDIDATES`` have their API keys
    configured, they are attached as fallbacks via LangChain's
    ``with_fallbacks()``.  On any runtime error from the primary the next
    available fallback is tried automatically.

    Args:
        temperature: Sampling temperature.  Results are cached per value.

    Returns:
        A LangChain :class:`~langchain_core.language_models.chat_models.BaseChatModel`
        (possibly wrapped with fallbacks).

    Raises:
        ValueError: If the primary ``LLM_PROVIDER`` is unsupported or not
            configured.
    """
    primary_name = (_runtime_provider_override or get_settings().LLM_PROVIDER).lower().strip()
    if primary_name not in _SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unknown LLM_PROVIDER={primary_name!r}. "
            f"Supported values: {', '.join(_SUPPORTED_PROVIDERS)}"
        )

    primary = _build_provider(primary_name, temperature)
    if primary is None:
        raise ValueError(
            f"LLM_PROVIDER={primary_name!r} is not configured — "
            f"check the required API key / path in .env"
        )

    fallbacks = [
        _build_provider(name, temperature)
        for name in _FAILOVER_CANDIDATES
        if name != primary_name
    ]
    fallbacks = [f for f in fallbacks if f is not None]

    if fallbacks:
        logger.info(
            "[llm.factory] primary=%s, fallbacks=%s",
            primary_name, [type(f).__name__ for f in fallbacks],
        )
        return primary.with_fallbacks(fallbacks)
    return primary
