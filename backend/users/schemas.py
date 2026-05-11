"""backend.users.schemas — Pydantic response models for user-facing API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class GuestAuthResponse(BaseModel):
    """Response returned by ``POST /auth/guest``."""

    id: str
    username: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    email_verified: bool
    avatar_url: Optional[str] = None
    auth_type: str
    is_new: bool


class ThreadSummary(BaseModel):
    """Compact summary of a user query thread for history and active-session endpoints."""

    thread_id: str
    query: str
    status: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    answer: Optional[str] = None


class QueryRequest(BaseModel):
    """Request body for ``POST /threads/query``."""

    query: str


class SseInfo(BaseModel):
    """Centrifugo SSE connection bootstrap info returned with a new query submission."""

    ws_url: str
    connection_token: str
    subscription_token: str
    channel: str


class QueryResponse(BaseModel):
    """Full status of a query thread."""

    thread_id: str
    status: str
    query: Optional[str] = None
    answer: Optional[str] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    sse: Optional[SseInfo] = None
    llm: Optional[SseInfo] = None


class TaskInfo(BaseModel):
    """Single task execution summary within a thread."""

    task_id: str
    thread_id: str
    node_id: Optional[str] = None
    node_name: str
    task_name: str
    status: str
    is_streaming: bool = False
    input: Optional[dict[str, Any]] = None
    output: Optional[dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SessionStatus(BaseModel):
    """Query record plus all its agent sub-tasks."""

    thread: QueryResponse
    tasks: list[TaskInfo]


class NodeExecutionInfo(BaseModel):
    """Single node execution summary within a thread."""

    node_id: str
    thread_id: str
    node_name: str
    status: str
    type: str = "Typical"
    parent_node_id: Optional[str] = None
    parallel_group: Optional[str] = None
    input: Optional[dict[str, Any]] = None
    output: Optional[dict[str, Any]] = None
    started_at: Optional[datetime] = None
    elapsed_ms: int = 0
    updated_at: Optional[datetime] = None


__all__ = [
    "GuestAuthResponse",
    "NodeExecutionInfo",
    "QueryRequest",
    "QueryResponse",
    "SessionStatus",
    "SseInfo",
    "TaskInfo",
    "ThreadSummary",
]
