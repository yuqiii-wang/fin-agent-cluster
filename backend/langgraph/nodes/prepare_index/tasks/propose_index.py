"""propose_index — pure-computation task for prepare_index.

Determines the set of equity market indexes to analyse for the current thread.

Logic
-----
1. Always include the six major global equity indexes (hard-coded).
2. Look up the proposed stock's registered index memberships in the DB.
3. If the stock belongs to an index not already in the default set, add it.
4. Return the resolved :class:`IndexCandidate` list so the node can run
   ``get_and_calculate_stats`` for each index ticker in parallel.

This is a pure computation task — no LLM or external I/O beyond DB reads.
Lifecycle tracking (``create_task`` / ``complete_task``) provides UI visibility
and audit trail.

Public exports
--------------
``propose_index``      — ``NodeTask`` instance used by ``AnalyzeIndexNode``.
``ProposeIndexInput``  — Input model.
``ProposeIndexOutput`` — Output model.
``IndexCandidate``     — Per-index metadata used by the node to dispatch stats.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from backend.db.postgres.queries.fin_markets_indexes import (
    get_index_by_code,
    get_symbol_index_codes,
    MarketIndex,
)
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask

logger = logging.getLogger(__name__)

_TASK_NAME = "propose_index"

# Hard-coded major global equity index codes (sourced from fin_markets.market_indexes).
_DEFAULT_INDEX_CODES: list[str] = [
    "SP500",
    "NASDAQ_100",
    "DOW_JONES",
    "FTSE_100",
    "HANG_SENG",
    "NIKKEI_225",
]

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class IndexCandidate(BaseModel):
    """Equity market index selected for stats analysis.

    Attributes:
        code:          Short identifier, e.g. ``'SP500'``.
        ticker:        Yahoo Finance ticker, e.g. ``'^GSPC'``.
        name:          Human-readable name, e.g. ``'S&P 500'``.
        currency_code: ISO 4217 code, e.g. ``'USD'``.
        zone:          Geographic zone: ``'amer'``, ``'emea'``, or ``'apac'``.
    """

    code: str = Field(description="Short identifier, e.g. 'SP500'.")
    ticker: str = Field(description="Yahoo Finance ticker, e.g. '^GSPC'.")
    name: str = Field(description="Human-readable name, e.g. 'S&P 500'.")
    currency_code: str = Field(description="ISO 4217 currency code.")
    zone: str = Field(description="Geographic zone: 'amer', 'emea', or 'apac'.")

class ProposeIndexInput(BaseModel):
    """Input for the propose_index task.

    Attributes:
        stock_symbol: Ticker symbol of the proposed stock (from query_node output).
                      Used to detect whether the stock's home index is already
                      covered by the default set.  Empty string disables the check.
    """

    stock_symbol: str = Field(
        default="",
        description="Ticker of the stock under analysis; used for index-coverage check.",
    )

class ProposeIndexOutput(BaseModel):
    """Output from the propose_index task.

    Attributes:
        indexes:       Ordered list of equity index candidates for stats analysis.
        default_codes: Hard-coded major index codes always included.
        added_code:    Extra index code added because the stock was not covered by
                       the default set.  ``None`` when already covered.
    """

    indexes: list[IndexCandidate] = Field(
        default_factory=list,
        description="Equity index candidates ordered: defaults first, then added stock index.",
    )
    default_codes: list[str] = Field(
        default_factory=list,
        description="Hard-coded default index codes.",
    )
    added_code: str | None = Field(
        default=None,
        description="Index code added for the stock's home index when not in defaults.",
    )

# ---------------------------------------------------------------------------
# LangGraph layer — @task (pure computation, DB reads only)
# ---------------------------------------------------------------------------

def _resolve_candidates(default_codes: list[str]) -> list[IndexCandidate]:
    """Return ``IndexCandidate`` objects for each code that is present in the cache.

    Silently skips codes not found in the in-process cache (e.g. cache not yet warmed).

    Args:
        default_codes: List of index codes to resolve.

    Returns:
        List of :class:`IndexCandidate` objects.
    """
    candidates: list[IndexCandidate] = []
    for code in default_codes:
        idx: MarketIndex | None = get_index_by_code(code)
        if idx is None or not idx.ticker:
            logger.error("[PI-003] Index code %r not found in cache — skipping.", code)
            continue
        candidates.append(
            IndexCandidate(
                code=idx.code,
                ticker=idx.ticker,
                name=idx.name,
                currency_code=idx.currency_code,
                zone=idx.zone,
            )
        )
    return candidates

async def _propose_index_task(
    task_input: TaskInput[ProposeIndexInput],
) -> TaskOutput[ProposeIndexOutput]:
    """LangGraph @task: resolve the equity index set for the current stock.

    Reads the stock's registered index memberships from the DB and supplements
    the hard-coded default set when the stock belongs to an index outside it.

    Args:
        task_input: Typed envelope with ``TaskContext`` and ``ProposeIndexInput``.

    Returns:
        ``TaskOutput`` wrapping ``ProposeIndexOutput``.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump()

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type="Stats",
    )
    try:
        inp = task_input.content
        default_codes: list[str] = list(_DEFAULT_INDEX_CODES)

        # Resolve the default index candidates from the in-process cache.
        candidates = _resolve_candidates(default_codes)

        added_code: str | None = None
        stock_sym = inp.stock_symbol.strip().upper()

        if stock_sym:
            # Fetch the stock's registered index memberships.
            stock_index_codes: frozenset[str] = await get_symbol_index_codes(stock_sym)
            default_set = frozenset(default_codes)

            # Find the first stock index not already in the default set.
            extra_codes = sorted(stock_index_codes - default_set)
            if extra_codes:
                added_code = extra_codes[0]
                extra_candidate = _resolve_candidates([added_code])
                if extra_candidate:
                    candidates.extend(extra_candidate)
                else:
                    logger.error(
                        "[PI-004] Stock %r index %r not in cache — cannot add.",
                        stock_sym, added_code,
                    )
                    added_code = None

        output = ProposeIndexOutput(
            indexes=candidates,
            default_codes=default_codes,
            added_code=added_code,
        )

        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            output_data=output.model_dump(),
            view_type="Stats",
        )
        return TaskOutput(ctx=ctx, content=output)

    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            failed=True, error=str(exc), view_type="Stats",
        )
        raise

# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

propose_index = NodeTask(
    name=_TASK_NAME,
    description=(
        "Resolve the equity market index set for the current stock analysis. "
        "Always includes the six major global indexes (S&P 500, Nasdaq 100, Dow Jones, "
        "FTSE 100, Hang Seng, Nikkei 225). Adds the stock's registered home index when "
        "it is not already covered by the defaults."
    ),
    input_type=ProposeIndexInput,
    output_type=ProposeIndexOutput,
    task_fn=_propose_index_task,
    handler=lambda _: (_ for _ in ()).throw(
        NotImplementedError("propose_index runs in-process; no Celery handler.")
    ),
)
