"""DB insert task for the decision_maker node.

Persists a :class:`~backend.graph.agents.decision_maker.models.output.DecisionReport`
to ``fin_strategies.reports`` and returns the full inserted row as a dict.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Optional

from backend.db.connection import raw_conn
from backend.db.queries.fin_agents import TaskSQL
from backend.db.queries.fin_markets_quant import OhlcvStatsSQL
from backend.db.queries.fin_strategies import ReportSQL
from backend.graph.agents.decision_maker.models.output import DecisionReport
from backend.graph.agents.task_keys import DM_DB_INSERT_REPORT
from backend.graph.utils.task_stream import complete_task, fail_task

logger = logging.getLogger(__name__)

_REPORT_FIELDS = (
    "short_term_technical_desc",
    "long_term_technical_desc",
    "news_desc",
    "basic_biz_desc",
    "industry_desc",
    "significant_event_desc",
    "short_term_risk_desc",
    "long_term_risk_desc",
    "short_term_growth_desc",
    "long_term_growth_desc",
    "recent_trade_anomalies",
    "likely_today_fall_desc",
    "likely_tom_fall_desc",
    "likely_short_term_fall_desc",
    "likely_long_term_fall_desc",
    "likely_today_rise_desc",
    "likely_tom_rise_desc",
    "likely_short_term_rise_desc",
    "likely_long_term_rise_desc",
)


async def _fetch_last_quote_id(symbol: str) -> Optional[int]:
    """Return the ``id`` of the most recent equity quant_stats bar for *symbol*.

    Prefers the ``1day`` granularity (the canonical last-price reference); falls
    back to ``15min`` if no daily bar is available.

    Args:
        symbol: Ticker symbol (e.g. ``'AAPL'``).

    Returns:
        Primary key of the matching ``fin_markets.quant_stats`` row, or ``None``.
    """
    async with raw_conn() as conn:
        for granularity in ("1day", "15min"):
            cur = await conn.execute(OhlcvStatsSQL.GET_LATEST_ID, (symbol.upper(), granularity))
            row = await cur.fetchone()
            if row:
                return row["id"]
    return None


async def _fetch_market_data_task_ids(thread_id: str) -> list[int]:
    """Return all ``fin_agents.tasks.id`` values created by market_data_collector.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        Ordered list of task primary keys, or an empty list.
    """
    async with raw_conn() as conn:
        cur = await conn.execute(
            TaskSQL.GET_IDS_BY_NODE, (thread_id, "market_data_collector")
        )
        rows = await cur.fetchall()
    return [row["id"] for row in rows]


async def run_db_insert(
    symbol: str,
    report: DecisionReport,
    thread_id: str,
    task_id: int,
) -> dict[str, Any]:
    """Insert a :class:`DecisionReport` into ``fin_strategies.reports``.

    Resolves ``last_quote_quant_stats_id`` from the most recent equity
    quant_stats bar for *symbol*, and collects ``market_data_task_ids`` from
    all ``market_data_collector`` tasks recorded for *thread_id*.

    Args:
        symbol:    Ticker symbol (maps to the ``symbol`` column).
        report:    Parsed decision report to persist.
        thread_id: LangGraph thread UUID (for task tracking).
        task_id:   Pre-created ``fin_agents.tasks`` row ID.

    Returns:
        The full inserted row as a dict (all columns from ``fin_strategies.reports``),
        or an empty dict on failure.
    """
    try:
        last_quote_id = await _fetch_last_quote_id(symbol)
        market_data_task_ids = await _fetch_market_data_task_ids(thread_id)

        async with raw_conn(search_path="fin_strategies,fin_agents") as conn:
            row = await conn.execute(
                ReportSQL.INSERT,
                (
                    symbol,
                    *(getattr(report, f) for f in _REPORT_FIELDS),
                    last_quote_id,
                    market_data_task_ids or None,
                ),
            )
            result = await row.fetchone()
            raw: dict[str, Any] = dict(result) if result else {}
            row_data: dict[str, Any] = {
                k: v.isoformat() if isinstance(v, (datetime, date)) else v
                for k, v in raw.items()
            }

        await complete_task(
            thread_id, task_id, DM_DB_INSERT_REPORT, row_data
        )
        report_id = row_data.get("id", -1)
        logger.info("[decision_maker/db_insert] report id=%d saved for %s", report_id, symbol)
        return row_data
    except Exception as exc:
        logger.warning("[decision_maker/db_insert] DB insert failed: %s", exc)
        await fail_task(thread_id, task_id, DM_DB_INSERT_REPORT, str(exc))
        return {}
