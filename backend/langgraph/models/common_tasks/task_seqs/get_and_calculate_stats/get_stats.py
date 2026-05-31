"""get_stats — NodeTask to fetch OHLCV stats for a symbol/period.

Resolves a :class:`~backend.resources.stats.models.StatsRecord` for the
requested ``(symbol, period)`` via one of three paths:

* ``json_input``   — directly inject a structured OHLCV matrix (or a full
  ``StatsRecord`` dict) handed down from a previous task; stored in
  ``fin_markets.input_raw`` and returned without any external call.
* ``text_content`` — inject free-form text (e.g. an analyst note); stored in
  ``input_raw`` and returned as a non-OHLCV stub (``data_type='text'``).
* external fetch    — request a stats provider (yfinance / FMP / mock) with
  provider- and period-fallback, caching the raw response in ``input_raw``.

Execution layers
----------------
LangGraph layer (``_get_stats_task`` decorated with ``@task``):
    Calls ``create_task(..., view_type="Stats")``, delegates to the Celery
    completion worker, and returns a ``TaskOutput``.

Celery layer (``_handler``):
    Dispatches to the injection or external-fetch path and caches the raw
    payload in ``fin_markets.input_raw``.

Public exports
--------------
``get_stats``       — ``NodeTask`` instance.
``GetStatsInput``   — Pydantic input model.
``GetStatsOutput``  — Pydantic output model.
``HANDLERS``        — dict slice for Celery handler registration.
"""

from __future__ import annotations

import hashlib
import json
import logging

from langgraph.func import task
from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.config import get_settings
from backend.db.postgres import raw_conn
from backend.db.postgres.queries.fin_markets_input_raw import InputRawSQL
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.errors.codes import (
    STATS_TASK_NO_DATA,
    STATS_TASK_PERIOD_FALLBACK,
    STATS_TASK_PROVIDER_ERROR,
)
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask, get_task_cache_ttl
from backend.resources.stats.client import StatsClient
from backend.resources.stats.models import StatsMatrix, StatsRecord
from backend.resources.stats.routing import provider_for_symbol

logger = logging.getLogger(__name__)

_TASK_NAME = "get_stats"
_NODE_NAME = "common_tasks/get_stats"
_METHOD = "list_stats"

# Period fallbacks: when a provider returns no bars for the requested period,
# retry with progressively shorter windows that are more likely to be populated.
PERIOD_FALLBACKS: dict[str, list[str]] = {
    "2y": ["1y"],
    "1y": ["3mo"],
    "3mo": ["1mo"],
    "1mo": ["1w"],
    "1w": ["1d"],
}

# Provider fallback chains: when the primary provider yields no data, try the
# next provider in the chain.
_PROVIDER_FALLBACK_CHAINS: dict[str, list[str]] = {
    "fmp":      ["fmp", "yfinance"],
    "yfinance": ["yfinance", "fmp"],
    "mock":     ["mock"],
}


def _build_provider_chain(symbol: str) -> list[str]:
    """Return the ordered provider list for stats fetching.

    Args:
        symbol: Normalised (uppercase) ticker symbol.

    Returns:
        Non-empty list of provider labels in priority order.
    """
    settings = get_settings()
    primary = provider_for_symbol(symbol) or (settings.STATS_PROVIDER or "mock").strip().lower()
    chain = _PROVIDER_FALLBACK_CHAINS.get(primary, [primary])
    if not settings.FMP_API_KEY:
        chain = [p for p in chain if p != "fmp"]
    return chain or ["mock"]


def _make_cache_key(source: str, method: str, symbol: str, period: str) -> str:
    """Compute a deterministic SHA-256 cache key for ``input_raw`` lookup.

    Args:
        source: Provider label, e.g. ``'yfinance'``, ``'fmp'``, ``'mock'``.
        method: Method/endpoint label, e.g. ``'list_stats'``.
        symbol: Normalised (uppercase) ticker.
        period: Aggregation period, e.g. ``'1mo'``.

    Returns:
        Hex-encoded 64-character SHA-256 digest.
    """
    payload = json.dumps(
        {"source": source, "method": method, "symbol": symbol, "period": period},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class GetStatsInput(BaseModel):
    """Input for the get_stats task.

    Attributes:
        symbol:                   Equity/instrument ticker, e.g. ``'AAPL'``.
        period:                   Aggregation period, e.g. ``'1d'``, ``'1mo'``.
        text_content: Free-form text to inject instead of fetching; produces a non-OHLCV stub record.
        json_input:   Structured OHLCV matrix or full ``StatsRecord`` dict handed down from a previous task.
        src_task_id:  Optional source task id for provenance.
        thread_id:    LangGraph thread id; forwarded to ``input_raw`` for provenance
                      (injected by the @task layer, not set by callers).
    """

    symbol: str = Field(description="Instrument ticker, e.g. 'AAPL'.")
    period: str = Field(default="1mo", description="Aggregation period, e.g. '1d', '1mo'.")
    text_content: str | None = Field(default=None, description="Free-form text to inject.")
    json_input: dict | None = Field(default=None, description="Injected OHLCV matrix or StatsRecord dict.")
    src_task_id: str | None = Field(default=None, description="Source task id for provenance.")
    thread_id: str | None = Field(default=None, description="Thread id for input_raw provenance.")


class GetStatsOutput(BaseModel):
    """Output from the get_stats task.

    Attributes:
        stats_record:     Resolved :class:`StatsRecord` (OHLCV matrix or stub).
        from_cache:       ``True`` when served from a fresh ``input_raw`` entry.
        data_type:        Payload category: ``'ohlcv'``, ``'text'``, ``'options'``, …
        bypass_calculate: ``True`` when downstream ``calculate_stats`` should be
                          short-circuited (non-OHLCV stub records).
    """

    stats_record: StatsRecord
    from_cache: bool = Field(default=False)
    data_type: str = Field(default="ohlcv")
    bypass_calculate: bool = Field(default=False)


# ---------------------------------------------------------------------------
# Celery layer — business logic
# ---------------------------------------------------------------------------


async def _persist(
    thread_id: str | None,
    symbol: str,
    source: str,
    method: str,
    cache_key: str,
    ttl_seconds: int,
    input_payload: dict,
    output_payload: dict,
) -> None:
    """Insert a raw payload into ``fin_markets.input_raw``.

    Args:
        thread_id:      LangGraph thread id for provenance (may be ``None``).
        symbol:         Normalised ticker.
        source:         Provider/source label.
        method:         Method/endpoint label.
        cache_key:      Deterministic cache key.
        ttl_seconds:    Per-row cache validity in seconds.
        input_payload:  Request params (JSON-serialisable).
        output_payload: Response/injected payload (JSON-serialisable).
    """
    async with raw_conn() as conn:
        await conn.execute(
            InputRawSQL.INSERT,
            (
                thread_id,
                _NODE_NAME,
                symbol,
                source,
                method,
                cache_key,
                ttl_seconds,
                json.dumps(input_payload),
                json.dumps(output_payload),
            ),
        )


def _build_stats_record(symbol: str, period: str, json_input: dict) -> StatsRecord:
    """Build a :class:`StatsRecord` from injected JSON.

    Accepts either a full ``StatsRecord`` dict (contains ``content``) or a bare
    :class:`StatsMatrix` dict (``timestamps`` + ``series``).

    Args:
        symbol:     Normalised ticker.
        period:     Aggregation period.
        json_input: Injected dict payload.

    Returns:
        A validated :class:`StatsRecord`.

    Raises:
        ValueError: When *json_input* is not a valid StatsRecord/StatsMatrix.
    """
    if "content" in json_input:
        try:
            return StatsRecord.model_validate(json_input)
        except Exception as exc:
            raise ValueError(
                f"[{STATS_TASK_PROVIDER_ERROR}] invalid StatsRecord json_input: {exc}"
            ) from exc
    try:
        matrix = StatsMatrix.model_validate(json_input)
    except Exception as exc:
        raise ValueError(
            f"[{STATS_TASK_PROVIDER_ERROR}] invalid stats matrix json_input: {exc}"
        ) from exc
    return StatsRecord(id=f"json-{symbol.lower()}-{period}", symbol=symbol, period=period, content=matrix)


async def _handle_json_input(inp: GetStatsInput, symbol: str) -> dict:
    """Inject a structured OHLCV/StatsRecord payload (no external call).

    Args:
        inp:    Typed input with a non-``None`` ``json_input``.
        symbol: Normalised ticker.

    Returns:
        Serialised :class:`GetStatsOutput` dict.
    """
    assert inp.json_input is not None
    data_type = str(inp.json_input.get("data_type", "ohlcv")) if isinstance(inp.json_input, dict) else "ohlcv"
    record = _build_stats_record(symbol, inp.period, inp.json_input)
    cache_key = _make_cache_key("injected", "json_input", symbol, inp.period)
    await _persist(
        inp.thread_id, symbol, "injected", "json_input", cache_key,
        get_task_cache_ttl(_TASK_NAME),
        {"symbol": symbol, "period": inp.period, "src_task_id": inp.src_task_id},
        {"stats_record": record.model_dump(mode="json"), "data_type": data_type},
    )
    return GetStatsOutput(
        stats_record=record,
        from_cache=False,
        data_type=data_type,
        bypass_calculate=data_type != "ohlcv",
    ).model_dump(mode="json")


async def _handle_text_input(inp: GetStatsInput, symbol: str) -> dict:
    """Inject free-form text as a non-OHLCV stub record (no external call).

    Args:
        inp:    Typed input with a non-empty ``text_content``.
        symbol: Normalised ticker.

    Returns:
        Serialised :class:`GetStatsOutput` dict.
    """
    record = StatsRecord(
        id=f"text-{symbol.lower()}-{inp.period}",
        symbol=symbol,
        period=inp.period,
        content=StatsMatrix(timestamps=[], series={}),
    )
    cache_key = _make_cache_key("injected", "text_input", symbol, inp.period)
    await _persist(
        inp.thread_id, symbol, "injected", "text_input", cache_key,
        get_task_cache_ttl(_TASK_NAME),
        {"symbol": symbol, "period": inp.period, "src_task_id": inp.src_task_id},
        {"stats_record": record.model_dump(mode="json"), "text_content": inp.text_content, "data_type": "text"},
    )
    return GetStatsOutput(
        stats_record=record,
        from_cache=False,
        data_type="text",
        bypass_calculate=True,
    ).model_dump(mode="json")


async def _handle_external_fetch(inp: GetStatsInput, symbol: str) -> dict:
    """Fetch OHLCV stats from a provider with provider/period fallback.

    Args:
        inp:    Typed input (no injection fields set).
        symbol: Normalised ticker.

    Returns:
        Serialised :class:`GetStatsOutput` dict.

    Raises:
        ValueError: When no provider/period combination returns data.
    """
    ttl_seconds = get_task_cache_ttl(_TASK_NAME)
    providers = _build_provider_chain(symbol)
    last_error: str | None = None

    for provider in providers:
        cache_key = _make_cache_key(provider, _METHOD, symbol, inp.period)

        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(InputRawSQL.GET_CACHED, (cache_key,))
            cached_row = await cur.fetchone()

        if cached_row is not None:
            record = StatsRecord.model_validate(cached_row["output"]["stats_record"])
            return GetStatsOutput(
                stats_record=record, from_cache=True, data_type="ohlcv", bypass_calculate=False,
            ).model_dump(mode="json")

        for period_try in [inp.period, *PERIOD_FALLBACKS.get(inp.period, [])]:
            try:
                client = StatsClient(symbol=symbol, force_provider=provider)
                try:
                    resp = await client.list_stats(symbol, period_try, limit=1)
                finally:
                    await client.aclose()
            except Exception as exc:
                last_error = str(exc)
                logger.error(
                    "[%s] symbol=%s provider=%s period=%s error=%s",
                    STATS_TASK_PROVIDER_ERROR, symbol, provider, period_try, exc,
                )
                continue

            if not resp.items:
                if period_try != inp.period:
                    logger.error(
                        "[%s] symbol=%s provider=%s period fallback %s yielded no bars",
                        STATS_TASK_PERIOD_FALLBACK, symbol, provider, period_try,
                    )
                continue

            record = resp.items[0]
            await _persist(
                inp.thread_id, symbol, provider, _METHOD, cache_key, ttl_seconds,
                {"symbol": symbol, "period": inp.period},
                {"stats_record": record.model_dump(mode="json")},
            )
            return GetStatsOutput(
                stats_record=record, from_cache=False, data_type="ohlcv", bypass_calculate=False,
            ).model_dump(mode="json")

    raise ValueError(
        f"[{STATS_TASK_NO_DATA}] No stats data for symbol={symbol} period={inp.period} "
        f"from any provider. Last error: {last_error}"
    )


async def _handler(payload: dict) -> dict:
    """Resolve a StatsRecord via injection or external fetch.

    Args:
        payload: Serialised :class:`GetStatsInput` dict.

    Returns:
        Serialised :class:`GetStatsOutput` dict.

    Raises:
        ValueError: When external fetch yields no data or injected JSON is invalid.
    """
    inp = GetStatsInput.model_validate(payload)
    symbol = inp.symbol.upper()

    if inp.json_input is not None:
        return await _handle_json_input(inp, symbol)
    if inp.text_content:
        return await _handle_text_input(inp, symbol)
    return await _handle_external_fetch(inp, symbol)


# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------


@task
async def _get_stats_task(
    task_input: TaskInput[GetStatsInput],
) -> TaskOutput[GetStatsOutput]:
    """LangGraph @task: delegates get_stats to the Celery completion worker.

    Args:
        task_input: Typed envelope with :class:`~backend.langgraph.models.models.TaskContext`
                    and :class:`GetStatsInput` content.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`GetStatsOutput`.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump(mode="json")
    payload["thread_id"] = ctx.thread_id

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type="Stats",
        stats_views=[],
    )
    try:
        result = await delegate_completion(
            ctx.thread_id, ctx.task_id, ctx.node_id, ctx.node_name, ctx.task_name, payload,
        )
    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            failed=True, error=str(exc),
        )
        raise

    output = GetStatsOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)


# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

get_stats: NodeTask[GetStatsInput, GetStatsOutput] = NodeTask(
    name=_TASK_NAME,
    description=(
        "Resolve an OHLCV StatsRecord for a symbol/period: inject a structured "
        "json_input or text_content from a previous task, or fetch from a stats "
        "provider (yfinance/FMP/mock) with provider- and period-fallback. The raw "
        "payload is cached in fin_markets.input_raw."
    ),
    input_type=GetStatsInput,
    output_type=GetStatsOutput,
    task_fn=_get_stats_task,
    handler=_handler,
    cache_ttl_seconds=3600,
)

HANDLERS: dict = {_TASK_NAME: _handler}

__all__ = [
    "get_stats",
    "GetStatsInput",
    "GetStatsOutput",
    "HANDLERS",
]
