"""backend.users.schemas — Pydantic response models for user-facing API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from backend.api.graph.topology import GraphTopologyResponse
from backend.langgraph.lifecycle.ids import strip_node_suffix


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


class ReExploreRequest(BaseModel):
    """Request body for ``POST /threads/{thread_id}/nodes/{node_id}/re-explore``.

    ``input_override`` is an optional mapping of GraphState field names to new
    values.  When provided the fields are merged into the forked checkpoint
    state before the branch is dispatched, allowing the user to change the
    inputs that the re-explored node will receive.
    """

    input_override: Optional[dict[str, Any]] = None


class RetryTaskRequest(BaseModel):
    """Request body for ``POST /threads/{thread_id}/tasks/{task_id}/retry``.

    Attributes:
        mode: Retry strategy.
            - ``"restart"`` — re-run with the original input unchanged.
            - ``"compact_and_continue"`` — streaming tasks only; injects
              compressed prior thinking as context so the LLM continues from
              a de-looped state rather than starting over.
    """

    mode: str = "restart"


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
    topology: Optional[GraphTopologyResponse] = None
    fork_version: Optional[int] = None


class TaskInfo(BaseModel):
    """Single task execution summary within a thread."""

    task_id: str
    thread_id: str
    node_id: Optional[str] = None
    node_name: str
    task_name: str
    status: str
    view_type: str = "ToolCall"
    stats_views: list[str] = Field(default_factory=list)
    is_streaming: bool = False
    view_schema: Optional[dict[str, Any]] = None
    input: Optional[dict[str, Any]] = None
    output: Optional[dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator("node_name", mode="before")
    @classmethod
    def _strip_node_name(cls, v: str) -> str:
        return strip_node_suffix(v)


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
    type: str = "Workflow"
    parent_node_id: Optional[str] = None
    parallel_group: Optional[str] = None
    # Fork versioning
    version: int = 0
    checkpoint_id: str = ""
    prev_node_ids: list[str] = []
    next_node_ids: list[str] = []
    task_ids: list[str] = []
    # Fork-point metadata
    is_forked: bool = False
    forked_from_version: Optional[int] = None
    # View rendering hints
    view_type: str = "Json"
    view_schema: dict[str, Any] = Field(default_factory=dict)
    stats_views: list[str] = Field(default_factory=list)
    # Execution payloads (sourced from JOIN with node_executions)
    input: Optional[dict[str, Any]] = None
    output: Optional[dict[str, Any]] = None
    started_at: Optional[datetime] = None
    elapsed_ms: int = 0
    updated_at: Optional[datetime] = None

    @field_validator("node_name", mode="before")
    @classmethod
    def _strip_node_name(cls, v: str) -> str:
        return strip_node_suffix(v)


class VersionGraphResponse(BaseModel):
    """Version graph data for a single fork branch.

    For version 0 (original run): ``fork_node`` is ``None``, ``source_version`` is ``None``.
    For version V > 0: ``fork_node`` is the ``is_forked=TRUE`` node that started the branch,
    ``source_version`` is the version it branched from, and ``nodes`` lists all nodes
    that executed in version V.
    """

    version: int
    thread_id: str
    fork_node: Optional[NodeExecutionInfo] = None
    source_version: Optional[int] = None
    nodes: list[NodeExecutionInfo] = []


__all__ = [
    "GuestAuthResponse",
    "NodeExecutionInfo",
    "QueryRequest",
    "QueryResponse",
    "ReExploreRequest",
    "SessionStatus",
    "SseInfo",
    "TaskInfo",
    "ThreadSummary",
    "VersionGraphResponse",
]
