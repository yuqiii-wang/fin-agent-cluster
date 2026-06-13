"""get_stats_utils -- product-specific handlers for the get_stats task.

Mirror of :mod:`calculation_utils` for the fetch side of the pipeline.
Organisation:

* :mod:`.models`              -- shared ``GetStatsInput`` / ``GetStatsOutput`` Pydantic models.
* :mod:`.common`              -- shared constants, cache key, provider chain,
                                 horizon normalisation, JSON-injection helpers.
* :mod:`.get_ohlcv_stats`     -- handler that fetches OHLCV bars via ``StatsClient``
                                 with provider + period fallback.
* :mod:`.get_options_stats`   -- handler that fetches options chains via
                                 ``StatsClient(force_product='options')``.
* :mod:`.get_futures_stats`   -- extension-point stub (futures bars currently
                                 route through :func:`get_ohlcv_stats_handler`).
* :mod:`.get_fundamental_stats` -- extension-point stub (fundamentals are not
                                   fetched through ``get_stats`` today).

Public exports
--------------
``GetStatsInput``               -- shared input Pydantic model.
``GetStatsOutput``              -- shared output Pydantic model.
``_handle_json_input``          -- async: persist injected JSON as a StatsRecord.
``_handle_text_input``          -- async: persist free-form text as a stub record.
``get_ohlcv_stats_handler``     -- async: fetch OHLCV StatsRecord.
``get_options_stats_handler``   -- async: fetch options-chain StatsRecord.
``handler``                     -- async: top-level dispatcher routing to
                                   JSON/text/OHLCV/options.
"""

from __future__ import annotations

from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils.common import (
    _TASK_NAME,
    _build_stats_record,
    _detect_pipeline,
    _make_cache_key,
    _persist,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils.models import (
    GetStatsInput,
    GetStatsOutput,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils.get_ohlcv_stats import (
    get_ohlcv_stats_handler,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils.get_options_stats import (
    get_options_stats_handler,
)
from backend.langgraph.models.task import get_task_cache_ttl
from backend.quant.stats import STATS_DATA_TYPE


async def _handle_json_input(inp: GetStatsInput, symbol: str) -> dict:
    """Inject a structured OHLCV/StatsRecord payload (no external call)."""
    assert inp.json_input is not None
    pipeline = _detect_pipeline(inp.json_input)
    record = _build_stats_record(symbol, inp.period, inp.json_input)
    cache_key = _make_cache_key("injected", "json_input", symbol, inp.period)
    await _persist(
        inp.thread_id, symbol, "injected", "json_input", cache_key,
        get_task_cache_ttl(_TASK_NAME),
        {"symbol": symbol, "period": inp.period, "src_task_id": inp.src_task_id},
        {"stats_record": record.model_dump(mode="json"), "pipeline": pipeline},
    )
    return GetStatsOutput(
        stats_record=record,
        from_cache=False,
        pipeline=pipeline,
    ).model_dump(mode="json")


async def _handle_text_input(inp: GetStatsInput, symbol: str) -> dict:
    """Inject free-form text as a stub record (no external call)."""
    from backend.resources.stats.models import StatsRecord as _SR

    record = _SR(
        id=f"text-{symbol.lower()}-{inp.period}",
        symbol=symbol,
        period=inp.period,
        content={},
    )
    cache_key = _make_cache_key("injected", "text_input", symbol, inp.period)
    await _persist(
        inp.thread_id, symbol, "injected", "text_input", cache_key,
        get_task_cache_ttl(_TASK_NAME),
        {"symbol": symbol, "period": inp.period, "src_task_id": inp.src_task_id},
        {
            "stats_record": record.model_dump(mode="json"),
            "text_content": inp.text_content,
            "pipeline": STATS_DATA_TYPE.TEXT.value,
        },
    )
    return GetStatsOutput(
        stats_record=record,
        from_cache=False,
        pipeline=STATS_DATA_TYPE.TEXT.value,
    ).model_dump(mode="json")


async def handler(payload: dict) -> dict:
    """Resolve a StatsRecord via injection or external fetch.

    Routing order:
      1. ``json_input`` present  -> :func:`_handle_json_input` (persists injected
         data; pipeline auto-detected as ``'ohlcv'`` or ``'options'``).
      2. ``text_content`` present -> :func:`_handle_text_input` (persists text
         stub; pipeline ``'text'``).
      3. otherwise, external fetch:
         - ``maturity_horizon is not None`` or ``period == 'options'`` ->
           :func:`get_options_stats_handler`.
         - anything else -> :func:`get_ohlcv_stats_handler`.

    Args:
        payload: Serialised :class:`GetStatsInput` dict.

    Returns:
        Serialised :class:`GetStatsOutput` dict.

    Raises:
        ValueError: When external fetch yields no data.
    """
    inp = GetStatsInput.model_validate(payload)
    symbol = inp.symbol.upper()

    if inp.json_input is not None:
        return await _handle_json_input(inp, symbol)
    if inp.text_content:
        return await _handle_text_input(inp, symbol)

    is_options_pipeline = inp.maturity_horizon is not None or inp.period == "options"
    if is_options_pipeline:
        return await get_options_stats_handler(inp, symbol)
    return await get_ohlcv_stats_handler(inp, symbol)


__all__ = [
    "GetStatsInput",
    "GetStatsOutput",
    "_handle_json_input",
    "_handle_text_input",
    "get_ohlcv_stats_handler",
    "get_options_stats_handler",
    "handler",
]
