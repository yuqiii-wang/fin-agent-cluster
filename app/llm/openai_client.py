"""OpenAI-compatible LLM client.

Works with OpenAI, Azure OpenAI, Ark (Volcano Engine), and any
provider exposing an OpenAI-compatible chat completions endpoint.
"""

from typing import Any

from langchain_openai import ChatOpenAI

from app.llm.base import LLMClientBase, LLMMessage, LLMResponse


class OpenAICompatibleClient(LLMClientBase):
    """LLM client for OpenAI-compatible APIs (OpenAI, Ark, vLLM, etc.)."""

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        model: str = "gpt-4o",
        default_temperature: float = 0.3,
    ) -> None:
        """Initialize OpenAI-compatible client.

        Args:
            api_key: API key for authentication.
            base_url: Custom API base URL (None for official OpenAI).
            model: Default model name.
            default_temperature: Default sampling temperature.
        """
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._default_temperature = default_temperature
        self._langchain_model = ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=default_temperature,
        )

    async def chat(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.3,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send chat completion via OpenAI-compatible API.

        Args:
            messages: Chat messages.
            temperature: Sampling temperature.
            max_tokens: Max tokens to generate.
            **kwargs: Additional parameters passed to the API.

        Returns:
            LLMResponse with content and usage metadata.
        """
        lc_messages = [(m.role, m.content) for m in messages]
        resp = await self._langchain_model.ainvoke(
            lc_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        usage = {}
        if hasattr(resp, "response_metadata") and resp.response_metadata:
            token_usage = resp.response_metadata.get("token_usage", {})
            usage = {
                "prompt_tokens": token_usage.get("prompt_tokens", 0),
                "completion_tokens": token_usage.get("completion_tokens", 0),
                "total_tokens": token_usage.get("total_tokens", 0),
            }
        return LLMResponse(
            content=resp.content if isinstance(resp.content, str) else str(resp.content),
            model=self._model,
            usage=usage,
        )

    async def close(self) -> None:
        """No persistent resources to release for LangChain OpenAI client."""
        pass

    def to_langchain_chat_model(self) -> ChatOpenAI:
        """Return the underlying LangChain ChatOpenAI instance.

        Returns:
            ChatOpenAI instance for direct use in LangGraph nodes.
        """
        return self._langchain_model
