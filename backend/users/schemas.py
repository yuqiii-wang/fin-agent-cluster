"""Pydantic request/response schemas for the users.queries route."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class QueryRequest(BaseModel):
    """Payload for submitting a new user query."""

    query: str


class QueryResponse(BaseModel):
    """Response returned after submitting or polling a query."""

    thread_id: str
    status: str
    report: Optional[str] = None
    error: Optional[str] = None


class TaskInfo(BaseModel):
    """Summary of a single agent sub-task."""

    id: int
    thread_id: str
    node_execution_id: Optional[int] = None
    node_name: str
    task_key: str
    status: str
    input: dict = {}
    output: dict = {}
    created_at: datetime
    updated_at: datetime


class SessionStatus(BaseModel):
    """Full status of a user session: the query record plus its tasks."""

    thread_id: str
    user_query_id: int
    status: str
    tasks: list[TaskInfo]


class NodeExecutionInfo(BaseModel):
    """Input/output snapshot for a single node execution."""

    id: int
    node_name: str
    input: dict
    output: dict
    started_at: datetime
    elapsed_ms: int


class StrategyReport(BaseModel):
    """Full strategy report row from ``fin_strategies.reports``, with associated tasks."""

    id: int
    symbol: str
    short_term_technical_desc: str
    long_term_technical_desc: str
    news_desc: str
    basic_biz_desc: str
    industry_desc: str
    significant_event_desc: Optional[str] = None
    short_term_risk_desc: Optional[str] = None
    long_term_risk_desc: Optional[str] = None
    short_term_growth_desc: Optional[str] = None
    long_term_growth_desc: Optional[str] = None
    recent_trade_anomalies: Optional[str] = None
    likely_today_fall_desc: Optional[str] = None
    likely_tom_fall_desc: Optional[str] = None
    likely_short_term_fall_desc: Optional[str] = None
    likely_long_term_fall_desc: Optional[str] = None
    likely_today_rise_desc: Optional[str] = None
    likely_tom_rise_desc: Optional[str] = None
    likely_short_term_rise_desc: Optional[str] = None
    likely_long_term_rise_desc: Optional[str] = None
    last_quote_quant_stats_id: Optional[int] = None
    market_data_task_ids: Optional[list[int]] = None
    created_at: datetime
    reference_tasks: list[TaskInfo] = []


class StrategyReportList(BaseModel):
    """Paginated list of strategy reports for a symbol."""

    symbol: str
    total: int
    reports: list[StrategyReport]


# ── Auth / User management ───────────────────────────────────────────────────


class GuestAuthResponse(BaseModel):
    """Returned by POST /auth/guest \u2014 and embedded in me/ profile responses."""

    id: str
    username: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    email_verified: bool = False
    avatar_url: Optional[str] = None
    auth_type: str
    is_new: bool


class ThreadSummary(BaseModel):
    """Lightweight summary of one user thread for the history panel."""

    thread_id: str
    query: str
    status: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    answer: Optional[str] = None


# ── Threads API — read/event endpoints ──────────────────────────────────────


class ThreadListResponse(BaseModel):
    """Paginated list of user query threads."""

    items: list[ThreadSummary]
    total: int
    limit: int
    offset: int


class LlmResponseRecord(BaseModel):
    """One persisted LLM completion record from ``fin_agents.llm_responses``."""

    id: int
    event_id: str
    ts: datetime
    provider: str
    model: str
    task_key: Optional[str] = None
    node_name: Optional[str] = None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    thinking: Optional[str] = None
    answer: Optional[str] = None


class LlmResponseList(BaseModel):
    """All LLM completion records for a thread."""

    thread_id: str
    records: list[LlmResponseRecord]


class ThreadStateResponse(BaseModel):
    """Latest LangGraph checkpoint state for a thread (read-only)."""

    thread_id: str
    checkpoint_id: Optional[str] = None
    state: dict[str, Any]


class EmitEventRequest(BaseModel):
    """Payload for manually publishing an SSE event to a thread channel."""

    event: str
    payload: dict[str, Any] = {}


class EmitEventResponse(BaseModel):
    """Result of a manual event publish."""

    thread_id: str
    event: str
    published: bool


class UpdateThreadStatusRequest(BaseModel):
    """Request to update a thread's DB status without triggering a graph run."""

    status: str
    error: Optional[str] = None
    emit_event: bool = True


class UpdateThreadStatusResponse(BaseModel):
    """Result of a thread status update."""

    thread_id: str
    status: str
    event_emitted: bool


class ResyncResponse(BaseModel):
    """Result of re-emitting current task/query state as Centrifugo events."""

    thread_id: str
    events_emitted: int
