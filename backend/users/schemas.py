"""Pydantic request/response schemas for the users.queries route."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class QueryRequest(BaseModel):
    """Payload for submitting a new financial analysis query."""

    query: str
    user_id: Optional[str] = None


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
