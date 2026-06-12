"""get_fundamentals — NodeTask to fetch one fundamental data endpoint.

Fetches fundamental data for a single endpoint type (income_statement,
balance_sheet, cash_flow, or key_metrics) from FMP or yfinance, caches
the raw response in ``fin_markets.input_raw`` with a 24-hour TTL, and
returns the raw JSON dict.

Execution layers
----------------
LangGraph layer (``_get_fundamentals_task`` decorated with ``@task``):
    Calls ``create_task(..., view_type="Fundamentals")``, delegates to the
    Celery completion worker, and returns a ``TaskOutput``.

Celery layer (``_handler``):
    1. Computes a deterministic SHA-256 cache key.
    2. Checks ``fin_markets.input_raw`` for a fresh entry (24-hour TTL).
    3. On cache miss: calls the appropriate provider fetcher.
    4. Inserts raw result into ``input_raw`` and returns ``GetFundamentalsOutput``.

Public exports
--------------
``get_fundamentals``         — ``NodeTask`` instance.
``GetFundamentalsInput``     — Pydantic input model.
``GetFundamentalsOutput``    — Pydantic output model.
``VALID_ENDPOINT_TYPES``     — Frozenset of supported endpoint type strings.
``HANDLERS``                 — dict slice for Celery handler registration.
"""

from __future__ import annotations

import hashlib
import json
import logging

from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.config import get_settings
from backend.db.postgres import raw_conn
from backend.db.postgres.queries.fin_markets_input_raw import InputRawSQL
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.errors.codes import (
    FUNDAMENTALS_TASK_FETCH_ERROR,
    FUNDAMENTALS_TASK_NO_DATA,
    FUNDAMENTALS_TASK_PROVIDER_ERROR,
)
from backend.langgraph.models.models import NodeContext, TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask
from backend.resources.stats.routing import provider_for_symbol

logger = logging.getLogger(__name__)

_TASK_NAME = "get_fundamentals"
_CACHE_TTL_HOURS = 24
_CACHE_TTL_SECONDS = _CACHE_TTL_HOURS * 3600

VALID_ENDPOINT_TYPES = frozenset({
    "income_statement",
    "balance_sheet",
    "cash_flow",
    "key_metrics",
})

_PROVIDER_FALLBACK_CHAINS: dict[str, list[str]] = {
    "fmp":      ["fmp", "yfinance"],
    "yfinance": ["yfinance", "fmp"],
    "mock":     ["yfinance"],
}

def _build_provider_chain(symbol: str) -> list[str]:
    """Return ordered provider list for fundamentals fetching.

    Args:
        symbol: Normalised (uppercase) ticker symbol.

    Returns:
        Non-empty list of provider labels in priority order.
    """
    settings = get_settings()
    primary = provider_for_symbol(symbol) or (settings.STATS_PROVIDER or "yfinance").strip().lower()
    if primary == "mock":
        primary = "yfinance"
    chain = _PROVIDER_FALLBACK_CHAINS.get(primary, [primary])
    if not settings.FMP_API_KEY:
        chain = [p for p in chain if p != "fmp"]
    return chain or ["yfinance"]

def _make_cache_key(source: str, symbol: str, endpoint_type: str) -> str:
    """Compute a deterministic SHA-256 cache key for ``input_raw`` lookup.

    Args:
        source:        Provider label, e.g. ``'fmp'``, ``'yfinance'``.
        symbol:        Normalised (uppercase) ticker.
        endpoint_type: Endpoint identifier, e.g. ``'income_statement'``.

    Returns:
        Hex-encoded 64-character SHA-256 digest.
    """
    payload = json.dumps(
        {"source": source, "method": "fundamentals", "symbol": symbol, "endpoint": endpoint_type},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()

# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------

class GetFundamentalsInput(BaseModel):
    """Input for the get_fundamentals task.

    Attributes:
        symbol:        Equity ticker symbol, e.g. ``'AAPL'``.
        endpoint_type: One of ``income_statement``, ``balance_sheet``,
                       ``cash_flow``, ``key_metrics``.
        thread_id:     LangGraph thread id; forwarded to ``input_raw`` for
                       provenance (injected by the @task layer, not set by callers).
    """

    symbol: str = Field(description="Equity ticker symbol, e.g. 'AAPL'.")
    endpoint_type: str = Field(
        description=(
            "Fundamental data endpoint: 'income_statement', 'balance_sheet', "
            "'cash_flow', or 'key_metrics'."
        )
    )
    thread_id: str | None = Field(default=None, description="Thread id for input_raw provenance.")

class GetFundamentalsOutput(BaseModel):
    """Output from the get_fundamentals task.

    Attributes:
        endpoint_type: Endpoint that was fetched.
        json_data:     Raw provider dict for this endpoint.
        from_cache:    ``True`` when the result was served from ``input_raw`` cache.
    """

    endpoint_type: str
    json_data: dict = Field(default_factory=dict)
    from_cache: bool = Field(default=False)

# ---------------------------------------------------------------------------
# Celery layer — business logic
# ---------------------------------------------------------------------------

async def _handler(payload: dict) -> dict:
    """Fetch one fundamental endpoint, caching the raw result in ``input_raw``.

    Args:
        payload: Serialised :class:`GetFundamentalsInput` dict.

    Returns:
        Serialised :class:`GetFundamentalsOutput` dict.

    Raises:
        ValueError: When all providers fail or return empty data.
    """
    inp = GetFundamentalsInput.model_validate(payload)
    symbol = inp.symbol.upper()
    endpoint_type = inp.endpoint_type

    if endpoint_type not in VALID_ENDPOINT_TYPES:
        raise ValueError(
            f"[{FUNDAMENTALS_TASK_FETCH_ERROR}] Unknown endpoint_type='{endpoint_type}'"
        )

    providers = _build_provider_chain(symbol)
    last_error: str | None = None

    for provider in providers:
        cache_key = _make_cache_key(provider, symbol, endpoint_type)

        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(InputRawSQL.GET_CACHED, (cache_key,))
            cached_row = await cur.fetchone()

        if cached_row is not None:
            json_data: dict = cached_row["output"]
            return GetFundamentalsOutput(
                endpoint_type=endpoint_type,
                json_data=json_data,
                from_cache=True,
            ).model_dump(mode="json")

        try:
            if provider == "fmp":
                from backend.httpx_client import make_fmp_async_client
                from backend.resources.stats.fmp.fundamentals_fetcher import fetch as fmp_fetch
                settings = get_settings()
                async with make_fmp_async_client(settings.FMP_API_KEY) as http:
                    json_data = await fmp_fetch(symbol, endpoint_type, http)
            else:
                from backend.resources.stats.yfinance.fundamentals_fetcher import fetch as yf_fetch
                json_data = await yf_fetch(symbol, endpoint_type)

        except ValueError as exc:
            last_error = str(exc)
            logger.error(
                "[%s] symbol=%s provider=%s endpoint=%s error=%s, trying next provider",
                FUNDAMENTALS_TASK_PROVIDER_ERROR, symbol, provider, endpoint_type, exc,
            )
            continue

        async with raw_conn() as conn:
            await conn.execute(
                InputRawSQL.INSERT,
                (
                    inp.thread_id,
                    "common_tasks/get_fundamentals",
                    symbol,
                    provider,
                    "fundamentals",
                    cache_key,
                    _CACHE_TTL_SECONDS,
                    json.dumps({"symbol": symbol, "endpoint_type": endpoint_type}),
                    json.dumps(json_data),
                ),
            )

        return GetFundamentalsOutput(
            endpoint_type=endpoint_type,
            json_data=json_data,
            from_cache=False,
        ).model_dump(mode="json")

    raise ValueError(
        f"[{FUNDAMENTALS_TASK_NO_DATA}] No fundamental data for symbol={symbol} "
        f"endpoint={endpoint_type} from any provider. Last error: {last_error}"
    )

# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------

async def _get_fundamentals_task(
    task_input: TaskInput[GetFundamentalsInput],
) -> TaskOutput[GetFundamentalsOutput]:
    """LangGraph @task: delegates get_fundamentals to the Celery completion worker.

    Args:
        task_input: Typed envelope with :class:`~backend.langgraph.models.models.TaskContext`
                    and :class:`GetFundamentalsInput` content.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`GetFundamentalsOutput`.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump(mode="json")
    payload["thread_id"] = ctx.thread_id

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type="Fundamentals",
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

    output = GetFundamentalsOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)

# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

get_fundamentals = NodeTask(
    name=_TASK_NAME,
    description=(
        "Fetch one fundamental data endpoint (income_statement, balance_sheet, cash_flow, "
        "or key_metrics) for a symbol from FMP or yfinance. Results are cached in "
        "fin_markets.input_raw with a 24-hour TTL."
    ),
    input_type=GetFundamentalsInput,
    output_type=GetFundamentalsOutput,
    task_fn=_get_fundamentals_task,
    handler=_handler,
)

HANDLERS: dict = {_TASK_NAME: _handler}

__all__ = [
    "get_fundamentals",
    "GetFundamentalsInput",
    "GetFundamentalsOutput",
    "VALID_ENDPOINT_TYPES",
    "HANDLERS",
]
