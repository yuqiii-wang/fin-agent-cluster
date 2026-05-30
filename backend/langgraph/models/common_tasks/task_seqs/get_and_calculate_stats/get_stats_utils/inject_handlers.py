"""inject_handlers — handlers for direct data injection paths in get_stats.

Both handlers bypass the external stats API by writing the caller-supplied
data directly to ``fin_markets.quant_raw`` and returning a stub or full
:class:`~get_stats.GetStatsOutput`.

Execution context: Celery layer (called from ``_handler``).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from backend.db.postgres import raw_conn
from backend.db.postgres.queries.fin_markets_quant import QuantRawSQL
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils.cache_key import (
    make_cache_key,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils.json_input_validation import (
    validate_json_input,
)
from backend.resources.stats.models import StatsMatrix, StatsRecord

if TYPE_CHECKING:
    from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats import (
        GetStatsInput,
        GetStatsOutput,
    )

logger = logging.getLogger(__name__)


async def handle_json_input(inp: "GetStatsInput") -> dict:
    """Store a structured ``json_input`` payload in ``quant_raw`` and return serialised output.

    Validates the payload via :func:`validate_json_input`, then writes it to
    ``fin_markets.quant_raw``.  For ``data_type='ohlcv'`` a proper
    :class:`~backend.resources.stats.models.StatsRecord` is returned so that
    downstream ``calculate_stats`` can compute technical indicators.  All other
    data types return a stub record with ``bypass_calculate=True``.

    Args:
        inp: Typed :class:`GetStatsInput` with a non-``None`` ``json_input`` field.

    Returns:
        Serialised :class:`GetStatsOutput` dict.

    Raises:
        ValueError: On schema validation failure.
    """
    # Import here to avoid circular; models are thin Pydantic-only.
    from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats import (
        GetStatsOutput,
    )

    validate_json_input(inp.json_input)  # type: ignore[arg-type]

    data_type: str = inp.json_input["data_type"]  # type: ignore[index]
    symbol = inp.symbol.upper()
    cache_key = make_cache_key("sandbox", f"json_input:{data_type}", symbol, inp.period)

    async with raw_conn() as conn:
        await conn.execute(
            QuantRawSQL.INSERT,
            (
                None,
                "common_tasks/get_stats",
                "sandbox",
                f"json_input:{data_type}",
                symbol,
                cache_key,
                json.dumps({"symbol": symbol, "period": inp.period, "data_type": data_type}),
                json.dumps(inp.json_input),
            ),
        )

    if data_type == "ohlcv":
        stats_record = StatsRecord(
            id=f"json-ohlcv-{symbol}-{inp.period}",
            symbol=symbol,
            period=inp.period,
            content=StatsMatrix(
                timestamps=inp.json_input["timestamps"],  # type: ignore[index]
                series=inp.json_input["series"],  # type: ignore[index]
            ),
        )
        return GetStatsOutput(
            stats_record=stats_record,
            news_articles=[],
            from_cache=False,
            bypass_calculate=False,
        ).model_dump(mode="json")

    stub_record = StatsRecord(
        id=f"json-{data_type}-{symbol}-{inp.period}",
        symbol=symbol,
        period=inp.period,
        content=StatsMatrix(timestamps=[], series={}),
    )
    return GetStatsOutput(
        stats_record=stub_record,
        news_articles=[],
        from_cache=False,
        bypass_calculate=True,
    ).model_dump(mode="json")


async def handle_text_input(inp: "GetStatsInput") -> dict:
    """Store pre-fetched ``text_content`` in ``quant_raw`` and return a stub output.

    The text is persisted under ``source='web_content'`` / ``method='text_input'``
    so that later tasks (e.g. LLM digest) can retrieve it.  ``bypass_calculate``
    is always ``True`` because no structured OHLCV series is available.

    Args:
        inp: Typed :class:`GetStatsInput` with a non-empty ``text_content`` field.

    Returns:
        Serialised :class:`GetStatsOutput` dict with ``bypass_calculate=True``.
    """
    from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats import (
        GetStatsOutput,
    )

    symbol = inp.symbol.upper()
    cache_key = make_cache_key("web_content", "text_input", symbol, inp.period)

    async with raw_conn() as conn:
        await conn.execute(
            QuantRawSQL.INSERT,
            (
                None,
                "common_tasks/get_stats",
                "web_content",
                "text_input",
                symbol,
                cache_key,
                json.dumps({"symbol": symbol, "period": inp.period}),
                json.dumps({"text_content": inp.text_content}),
            ),
        )

    stub_record = StatsRecord(
        id=f"text-{symbol}-{inp.period}",
        symbol=symbol,
        period=inp.period,
        content=StatsMatrix(timestamps=[], series={}),
    )
    return GetStatsOutput(
        stats_record=stub_record,
        news_articles=[],
        from_cache=False,
        bypass_calculate=True,
    ).model_dump(mode="json")


__all__ = ["handle_json_input", "handle_text_input"]
