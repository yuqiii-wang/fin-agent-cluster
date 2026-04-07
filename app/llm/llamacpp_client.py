"""llama.cpp local model LLM client.

Supports local GGUF models via llama-cpp-python, enabling fully
offline inference without external API dependencies.

Requires: pip install llama-cpp-python
"""

from typing import Any

from app.llm.base import LLMClientBase, LLMMessage, LLMResponse


class LlamaCppClient(LLMClientBase):
    """LLM client for local llama.cpp models (GGUF format)."""

    def __init__(
        self,
        model_path: str,
        n_ctx: int = 4096,
        n_gpu_layers: int = -1,
        verbose: bool = False,
    ) -> None:
        """Initialize llama.cpp client with a local GGUF model.

        Args:
            model_path: Path to the GGUF model file.
            n_ctx: Context window size in tokens.
            n_gpu_layers: Number of layers to offload to GPU (-1 = all).
            verbose: Enable llama.cpp verbose logging.
        """
        try:
            from llama_cpp import Llama
        except ImportError:
            raise ImportError(
                "llama-cpp-python is required for local model support. "
                "Install with: pip install llama-cpp-python"
            )

        self._model_path = model_path
        self._llm = Llama(
            model_path=model_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            verbose=verbose,
            chat_format="chatml",
        )

    async def chat(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.3,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Run chat completion locally via llama.cpp.

        Args:
            messages: Chat messages.
            temperature: Sampling temperature.
            max_tokens: Max tokens to generate (default: 512).
            **kwargs: Additional parameters for llama.cpp.

        Returns:
            LLMResponse with generated content.
        """
        formatted = [{"role": m.role, "content": m.content} for m in messages]

        # llama-cpp-python is synchronous; run in thread to not block event loop
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._llm.create_chat_completion(
                messages=formatted,
                temperature=temperature,
                max_tokens=max_tokens or 512,
                **kwargs,
            ),
        )

        content = ""
        if result.get("choices"):
            content = result["choices"][0].get("message", {}).get("content", "")

        usage_data = result.get("usage", {})
        return LLMResponse(
            content=content,
            model=self._model_path,
            usage={
                "prompt_tokens": usage_data.get("prompt_tokens", 0),
                "completion_tokens": usage_data.get("completion_tokens", 0),
                "total_tokens": usage_data.get("total_tokens", 0),
            },
            raw=result,
        )

    async def close(self) -> None:
        """Release llama.cpp model resources."""
        if self._llm:
            del self._llm
            self._llm = None  # type: ignore[assignment]

    def to_langchain_chat_model(self) -> Any:
        """Return a LangChain-compatible ChatLlamaCpp wrapper.

        Returns:
            ChatLlamaCpp instance or None if langchain-community not installed.
        """
        try:
            from langchain_community.chat_models import ChatLlamaCpp
            return ChatLlamaCpp(
                model_path=self._model_path,
                temperature=0.3,
            )
        except ImportError:
            return None
