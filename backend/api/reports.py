"""FastAPI router for strategy report endpoints.

Mounted at ``/reports`` under the parent API router, so full paths are:

    GET /api/v1/reports/symbol/{symbol}          latest report for a symbol
    GET /api/v1/reports/{report_id}              single report by id
    GET /api/v1/reports/symbol/{symbol}/list     paginated list for a symbol
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from backend.db import raw_conn
from backend.db.queries.fin_agents import TaskSQL
from backend.db.queries.fin_strategies import ReportSQL
from backend.users.schemas import StrategyReport, StrategyReportList, TaskInfo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])

_SEARCH_PATH = "fin_strategies,fin_agents"


def _row_to_task(row: dict) -> TaskInfo:
    """Convert a DB row dict to a TaskInfo schema.

    Args:
        row: Dictionary representing a single ``fin_agents.tasks`` row.

    Returns:
        Populated TaskInfo instance.
    """
    return TaskInfo(
        id=row["id"],
        thread_id=row["thread_id"],
        node_execution_id=row["node_execution_id"],
        node_name=row["node_name"],
        task_key=row["task_key"],
        status=row["status"],
        input=row["input"] or {},
        output=row["output"] or {},
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_report(row: dict, tasks: list[TaskInfo]) -> StrategyReport:
    """Convert a DB row dict to a StrategyReport schema.

    Args:
        row:   Dictionary representing a single ``fin_strategies.reports`` row.
        tasks: Pre-fetched reference tasks for the References section.

    Returns:
        Populated StrategyReport instance.
    """
    return StrategyReport(
        id=row["id"],
        symbol=row["symbol"],
        short_term_technical_desc=row["short_term_technical_desc"],
        long_term_technical_desc=row["long_term_technical_desc"],
        news_desc=row["news_desc"],
        basic_biz_desc=row["basic_biz_desc"],
        industry_desc=row["industry_desc"],
        significant_event_desc=row["significant_event_desc"],
        short_term_risk_desc=row["short_term_risk_desc"],
        long_term_risk_desc=row["long_term_risk_desc"],
        short_term_growth_desc=row["short_term_growth_desc"],
        long_term_growth_desc=row["long_term_growth_desc"],
        recent_trade_anomalies=row["recent_trade_anomalies"],
        likely_today_fall_desc=row["likely_today_fall_desc"],
        likely_tom_fall_desc=row["likely_tom_fall_desc"],
        likely_short_term_fall_desc=row["likely_short_term_fall_desc"],
        likely_long_term_fall_desc=row["likely_long_term_fall_desc"],
        likely_today_rise_desc=row["likely_today_rise_desc"],
        likely_tom_rise_desc=row["likely_tom_rise_desc"],
        likely_short_term_rise_desc=row["likely_short_term_rise_desc"],
        likely_long_term_rise_desc=row["likely_long_term_rise_desc"],
        last_quote_quant_stats_id=row["last_quote_quant_stats_id"],
        market_data_task_ids=row["market_data_task_ids"],
        created_at=row["created_at"],
        reference_tasks=tasks,
    )


async def _fetch_reference_tasks(task_ids: list[int] | None) -> list[TaskInfo]:
    """Fetch tasks by IDs and return as TaskInfo list.

    Args:
        task_ids: Optional list of task primary keys to fetch.

    Returns:
        List of TaskInfo; empty if task_ids is None or empty.
    """
    if not task_ids:
        return []
    async with raw_conn(search_path=_SEARCH_PATH) as conn:
        cur = await conn.execute(TaskSQL.GET_BY_IDS, (task_ids,))
        rows = await cur.fetchall()
    return [_row_to_task(r) for r in rows]


@router.get("/symbol/{symbol}", response_model=StrategyReport)
async def get_latest_report(symbol: str) -> StrategyReport:
    """Return the most recent strategy report for *symbol*.

    Args:
        symbol: Ticker symbol, e.g. ``AAPL``.

    Raises:
        HTTPException 404: No report exists for the symbol.
    """
    async with raw_conn(search_path=_SEARCH_PATH) as conn:
        cur = await conn.execute(ReportSQL.GET_LATEST_BY_SYMBOL, (symbol.upper(),))
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No report found for symbol '{symbol}'")
    tasks = await _fetch_reference_tasks(row["market_data_task_ids"])
    return _row_to_report(row, tasks)


@router.get("/{report_id}", response_model=StrategyReport)
async def get_report_by_id(report_id: int) -> StrategyReport:
    """Return a strategy report by its primary key.

    Args:
        report_id: Primary key of the report row.

    Raises:
        HTTPException 404: Report with given id does not exist.
    """
    async with raw_conn(search_path=_SEARCH_PATH) as conn:
        cur = await conn.execute(ReportSQL.GET_BY_ID, (report_id,))
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found")
    tasks = await _fetch_reference_tasks(row["market_data_task_ids"])
    return _row_to_report(row, tasks)


@router.get("/symbol/{symbol}/list", response_model=StrategyReportList)
async def list_reports(
    symbol: str,
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> StrategyReportList:
    """Return a paginated list of strategy reports for *symbol*.

    Args:
        symbol: Ticker symbol.
        limit:  Maximum rows to return (1-100, default 10).
        offset: Row offset for pagination.

    Returns:
        StrategyReportList with reports and total count.
    """
    async with raw_conn(search_path=_SEARCH_PATH) as conn:
        cur = await conn.execute(ReportSQL.LIST_BY_SYMBOL, (symbol.upper(), limit, offset))
        rows = await cur.fetchall()
    reports: list[StrategyReport] = []
    for row in rows:
        tasks = await _fetch_reference_tasks(row["market_data_task_ids"])
        reports.append(_row_to_report(row, tasks))
    return StrategyReportList(symbol=symbol.upper(), total=len(reports), reports=reports)

