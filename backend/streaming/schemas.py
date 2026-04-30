"""Pydantic message schemas for Redis Streams topics.

LLMCompletionMessage is the only active stream message schema.
All other stream message types (graph events, market ticks, trade signals,
news enrichment) have been removed along with their corresponding workers.

When consuming, reconstruct the model with ``Model.model_validate(fields)``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class StreamKey(str, Enum):
    """Human-readable stream key names used in the HTTP API.

    Maps to the actual Redis stream name via
    ``backend.streaming.streams.STREAM_KEY_MAP``.
    """

    LLM_COMPLETIONS = "llm-completions"


class BaseStreamMessage(BaseModel):
    """Common envelope fields shared by all stream message types.

    Attributes:
        event_id: UUID4 string — unique identifier for idempotent processing.
        ts:       UTC timestamp when the message was produced.
    """

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# LLM completion events — emitted by llm.factory callback
# ---------------------------------------------------------------------------


class LLMCompletionMessage(BaseStreamMessage):
    """Token usage and latency record for a single LLM completion.

    Attributes:
        thread_id:         Originating LangGraph thread.
        provider:          LLM provider name (``'ollama'``, ``'ark'``, etc.).
        model:             Model identifier string.
        task_key:          Agent sub-task that triggered the completion.
        node_name:         Agent node name.
        prompt_tokens:     Input token count.
        completion_tokens: Output token count.
        total_tokens:      Sum of prompt + completion tokens.
        latency_ms:        Wall-clock time from request to first token.
        prompts:           Serialised input messages sent to the LLM.
        thinking:          Chain-of-thought / reasoning text (where supported).
        answer:            Final response text returned by the LLM.
    """

    thread_id: Optional[str] = None
    provider: str = ""
    model: str = ""
    task_key: Optional[str] = None
    node_name: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    prompts: Optional[str] = None
    thinking: Optional[str] = None
    answer: Optional[str] = None


# ---------------------------------------------------------------------------
# HTTP API response models
# ---------------------------------------------------------------------------


class StreamInfoResponse(BaseModel):
    """Metadata about a stream returned by the info endpoint.

    Attributes:
        stream_key: Human-readable key.
        stream:     Internal Redis stream name.
        length:     Current number of entries.
    """

    stream_key: StreamKey
    stream: str
    length: int
