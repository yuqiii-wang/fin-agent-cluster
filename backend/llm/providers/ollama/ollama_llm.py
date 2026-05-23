"""Ollama chat model provider — pure HTTP streaming via httpx."""

from __future__ import annotations

import json
import logging
import uuid
import urllib.parse
from collections.abc import AsyncIterator
from typing import Any, Optional, Sequence, Union

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from backend.config import get_settings

logger = logging.getLogger(__name__)

# Hostnames that should never be routed through a proxy.
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _to_ollama_messages(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    """Convert LangChain messages to Ollama /api/chat format.

    Handles tool-call assistant turns and tool result turns so the agent loop
    works correctly: AIMessage with tool_calls is serialised with the
    ``tool_calls`` field; ToolMessage is serialised as role ``"tool"`` with
    the tool function name extracted from the content.

    Args:
        messages: LangChain message list.

    Returns:
        List of Ollama-compatible message dicts for the /api/chat endpoint.
    """
    result = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            result.append({"role": "user", "content": str(msg.content)})
        elif isinstance(msg, SystemMessage):
            result.append({"role": "system", "content": str(msg.content)})
        elif isinstance(msg, ToolMessage):
            # Ollama expects role="tool" with optional name field.
            result.append({
                "role": "tool",
                "content": str(msg.content),
                "tool_call_id": msg.tool_call_id,
            })
        elif isinstance(msg, AIMessage):
            entry: dict[str, Any] = {
                "role": "assistant",
                "content": str(msg.content) if msg.content else "",
            }
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["args"],
                        }
                    }
                    for tc in msg.tool_calls
                ]
            result.append(entry)
        else:
            result.append({"role": "assistant", "content": str(msg.content)})
    return result


class OllamaLLM(BaseChatModel):
    """Ollama chat model using pure HTTP streaming.

    Streams tokens from the Ollama ``/api/chat`` endpoint via httpx NDJSON.
    ``provider`` and ``model`` are exposed as instance fields so the streaming
    infrastructure can persist them to DB without any hardcoding.

    Ollama streaming API
    --------------------
    POST ``/api/chat`` with ``{"model": "...", "messages": [...], "stream": true}``.
    Each response line is NDJSON::

        {"model": "...", "message": {"role": "assistant", "content": "<token>", "thinking": "<thinking_token>"}, "done": false}

    The final line has ``"done": true``.  Thinking models (e.g. Qwen3) send
    thinking tokens in ``message.thinking`` with an empty ``message.content``
    during the reasoning phase.  ``_astream`` wraps those tokens inside
    ``<think>…</think>`` tags so the downstream ``_extract_thinking_answer``
    in ``stream_task`` can split them from the answer text without changes to
    the broader pipeline.

    Proxy handling
    --------------
    When ``HTTP_PROXY`` is set, loopback destinations (``localhost``,
    ``127.0.0.1``, ``::1``) are always excluded so a locally-running Ollama
    instance is never routed through the proxy.

    Attributes:
        provider:   Always ``"ollama"`` — read by stream infrastructure for DB storage.
        model:      Ollama model name, e.g. ``"qwen3.5-27b-instruct"``.
        base_url:   Ollama HTTP base URL, e.g. ``"http://localhost:11434"``.
        http_proxy: Optional HTTP proxy URL forwarded to httpx (loopback excluded).
    """

    provider: str = "ollama"
    model: str
    base_url: str
    http_proxy: Optional[str] = None
    num_gpu: int = 65

    @property
    def _llm_type(self) -> str:
        return "ollama"

    def _resolved_proxy(self) -> str | None:
        """Return the proxy URL, or ``None`` when ``base_url`` is a loopback address."""
        if not self.http_proxy:
            return None
        host = urllib.parse.urlparse(self.base_url).hostname or ""
        if host in _LOOPBACK_HOSTS:
            return None
        return self.http_proxy

    def bind_tools(
        self,
        tools: Sequence[Union[dict[str, Any], type, Any, BaseTool]],
        **kwargs: Any,
    ) -> Runnable:
        """Bind tools to this LLM so they are passed to the Ollama API.

        Converts LangChain tool objects to OpenAI/Ollama function-call format
        and returns a new Runnable with the tools embedded as bound kwargs.

        Args:
            tools:  LangChain tools, callables, Pydantic models, or raw dicts.
            **kwargs: Additional kwargs forwarded to :py:meth:`bind`.

        Returns:
            A :class:`Runnable` that will pass ``tools`` to ``/api/chat``.
        """
        ollama_tools = [convert_to_openai_tool(t) for t in tools]
        return self.bind(tools=ollama_tools, **kwargs)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Synchronous (non-streaming) generation via blocking httpx.

        Called by LangChain's ``invoke`` / thread-executor path.  Uses
        ``stream: false`` so the full response arrives in one JSON object.
        When ``tools`` are present in ``kwargs`` (injected by
        :py:meth:`bind_tools`), they are forwarded to the Ollama API and any
        ``tool_calls`` in the response are parsed into the returned
        :class:`~langchain_core.messages.AIMessage`.

        Args:
            messages:    LangChain messages.
            stop:        Optional stop sequences.
            run_manager: LangChain callback manager (unused).
            **kwargs:    May include ``tools`` list from :py:meth:`bind_tools`.

        Returns:
            ``ChatResult`` wrapping the full assistant message.
        """
        ollama_messages = _to_ollama_messages(messages)
        options: dict[str, Any] = {"num_gpu": self.num_gpu}
        if stop:
            options["stop"] = stop
        request_body: dict[str, Any] = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": False,
            "options": options,
        }
        if "tools" in kwargs:
            request_body["tools"] = kwargs["tools"]
        if "tool_choice" in kwargs:
            request_body["tool_choice"] = kwargs["tool_choice"]
        if "format" in kwargs:
            request_body["format"] = kwargs["format"]

        url = f"{self.base_url}/api/chat"
        proxy = self._resolved_proxy()
        try:
            with httpx.Client(proxy=proxy, timeout=httpx.Timeout(300.0)) as client:
                resp = client.post(url, json=request_body)
                if resp.status_code >= 400:
                    logger.error(
                        "[OllamaLLM] HTTP %d from %s — %s",
                        resp.status_code, url, resp.text[:300],
                    )
                    resp.raise_for_status()
                data = resp.json()
                msg_data = data.get("message", {})
                content = msg_data.get("content", "")
                raw_tool_calls = msg_data.get("tool_calls", [])
        except httpx.ConnectError as exc:
            logger.error("[OllamaLLM] cannot connect to Ollama at %s — is it running? %s", url, exc)
            raise
        except httpx.TimeoutException as exc:
            logger.error("[OllamaLLM] request to %s timed out: %s", url, exc)
            raise

        if raw_tool_calls:
            tool_calls = [
                {
                    "id": f"call_{uuid.uuid4().hex[:8]}",
                    "name": tc["function"]["name"],
                    "args": tc["function"].get("arguments", {}),
                    "type": "tool_call",
                }
                for tc in raw_tool_calls
            ]
            ai_msg = AIMessage(content=content, tool_calls=tool_calls)
        else:
            ai_msg = AIMessage(content=content)
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Fall back to the sync path when tools are bound.

        ``_astream`` emits content tokens only; Ollama tool_calls are present
        only on the non-streaming ``/api/chat`` response.  When ``tools`` is in
        ``kwargs`` run ``_generate`` in a thread pool to avoid blocking the
        event loop while ensuring tool_calls propagate correctly.
        """
        import asyncio
        if "tools" in kwargs:
            return await asyncio.to_thread(
                lambda: self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
            )
        return await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Stream tokens from Ollama /api/chat using pure HTTP NDJSON.

        Each NDJSON line carries ``message.content`` (answer token) and/or
        ``message.thinking`` (thinking token).  Thinking models (e.g. Qwen3)
        send thinking tokens exclusively in ``message.thinking`` with an empty
        ``message.content`` during the reasoning phase; the answer tokens follow
        in ``message.content`` with an empty ``message.thinking``.

        Thinking tokens are re-wrapped as ``<think>…</think>`` inline so that
        the downstream ``_extract_thinking_answer`` in ``stream_task`` can split
        them from the answer without any changes to the streaming pipeline.

        Proxy handling: loopback ``base_url`` (localhost / 127.0.0.1) always
        bypasses the configured proxy via ``_resolved_proxy()``.

        Args:
            messages:    LangChain messages to send to the model.
            stop:        Optional stop sequences passed to Ollama.
            run_manager: LangChain callback manager (unused).

        Yields:
            ChatGenerationChunk for each non-empty content or thinking token.
        """
        ollama_messages = _to_ollama_messages(messages)
        options: dict[str, Any] = {"num_gpu": self.num_gpu}
        if stop:
            options["stop"] = stop
        request_body: dict[str, Any] = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": True,
            "options": options,
        }

        url = f"{self.base_url}/api/chat"
        proxy = self._resolved_proxy()
        in_thinking = False
        try:
            async with httpx.AsyncClient(proxy=proxy, timeout=httpx.Timeout(300.0)) as client:
                async with client.stream("POST", url, json=request_body) as resp:
                    if resp.status_code >= 400:
                        body = await resp.aread()
                        logger.error(
                            "[OllamaLLM] HTTP %d from %s — %s",
                            resp.status_code, url, body.decode(errors="replace")[:300],
                        )
                        resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            logger.error("[OllamaLLM] failed to parse NDJSON line: %r", line[:120])
                            continue
                        if data.get("done"):
                            if in_thinking:
                                try:
                                    yield ChatGenerationChunk(message=AIMessageChunk(content="</think>"))
                                except GeneratorExit:
                                    return
                            break
                        msg = data.get("message", {})
                        thinking = msg.get("thinking", "")
                        content = msg.get("content", "")
                        if thinking:
                            if not in_thinking:
                                in_thinking = True
                                thinking = "<think>" + thinking
                            try:
                                yield ChatGenerationChunk(message=AIMessageChunk(content=thinking))
                            except GeneratorExit:
                                return
                        elif content:
                            if in_thinking:
                                in_thinking = False
                                content = "</think>" + content
                            try:
                                yield ChatGenerationChunk(message=AIMessageChunk(content=content))
                            except GeneratorExit:
                                return
        except httpx.ConnectError as exc:
            logger.error("[OllamaLLM] cannot connect to Ollama at %s — is it running? %s", url, exc)
            raise
        except httpx.TimeoutException as exc:
            logger.error("[OllamaLLM] request to %s timed out: %s", url, exc)
            raise


def get_ollama_llm() -> OllamaLLM:
    """Return an OllamaLLM instance configured from settings."""
    settings = get_settings()
    return OllamaLLM(
        model=settings.OLLAMA_LLM_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        http_proxy=settings.HTTP_PROXY,
        num_gpu=settings.OLLAMA_NUM_GPU,
    )


__all__ = ["OllamaLLM", "get_ollama_llm"]
