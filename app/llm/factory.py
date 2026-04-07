"""LLM client factory — builds the appropriate client from config.

Supports:
  - "openai" / "ark" / "azure" → OpenAICompatibleClient
  - "llamacpp" → LlamaCppClient
"""

from app.config import get_settings
from app.llm.base import LLMClientBase


def create_llm_client(provider: str | None = None) -> LLMClientBase:
    """Create an LLM client based on provider name or settings.

    Args:
        provider: Provider name override. If None, infers from config.
            Supported: 'openai', 'ark', 'azure', 'llamacpp'.

    Returns:
        Configured LLMClientBase instance.

    Raises:
        ValueError: If provider is unsupported or required config is missing.
    """
    settings = get_settings()
    provider = (provider or getattr(settings, "LLM_PROVIDER", "openai")).lower()

    if provider in ("openai", "ark", "azure"):
        from app.llm.openai_client import OpenAICompatibleClient

        return OpenAICompatibleClient(
            api_key=settings.ARK_API_KEY,
            base_url=settings.ARK_BASE_URL,
            model=settings.ARK_MODEL,
        )
    elif provider == "llamacpp":
        from app.llm.llamacpp_client import LlamaCppClient

        model_path = getattr(settings, "LLAMACPP_MODEL_PATH", None)
        if not model_path:
            raise ValueError("LLAMACPP_MODEL_PATH must be set in .env for llamacpp provider")
        return LlamaCppClient(
            model_path=model_path,
            n_ctx=getattr(settings, "LLAMACPP_N_CTX", 4096),
            n_gpu_layers=getattr(settings, "LLAMACPP_N_GPU_LAYERS", -1),
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")


def get_langchain_chat_model():
    """Get a LangChain ChatModel from the default LLM client.

    Returns:
        LangChain-compatible chat model for use in prompt chains and LangGraph nodes.
    """
    client = create_llm_client()
    lc_model = client.to_langchain_chat_model()
    if lc_model is None:
        raise RuntimeError(f"LangChain integration not available for provider")
    return lc_model
