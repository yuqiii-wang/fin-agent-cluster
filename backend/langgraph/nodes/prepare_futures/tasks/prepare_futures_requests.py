"""prepare_futures_requests -- first task executed by prepare_futures.

Proposes the full catalogue of maturity windows that
:class:`~backend.quant.stats.constants.FUTURES_PERIODS` knows
about.  Each window is emitted in two shapes:

* :class:`~backend.langgraph.nodes.prepare_options.models.MaturityRequest`
  (short form: label / display_name / seconds / pipeline).
* :class:`~backend.langgraph.nodes.prepare_options.models.PrepareOptionsRequestItem`
  (``get_and_calculate_stats`` ready: symbol / period / pipeline /
  maturity_horizon).

``maturity_horizon`` is intentionally **not** part of the task input: the
hosting :class:`PrepareFuturesNode` owns the horizon and decides which of
the proposed windows to actually run.

Life-cycle
----------
1. ``create_task`` + ``complete_task`` provide UI visibility and audit
   trail -- the task is pure computation (no LLM / external I/O).
2. Returns a :class:`PrepareOptionsRequestsOutput` with the full
   catalogue; the node then fans out a ``get_and_calculate_stats`` call
   for each window that fits within its own ``maturity_horizon``.

Public exports
--------------
``prepare_futures_requests`` -- ``NodeTask`` instance used by ``PrepareFuturesNode``.
``HANDLERS``                         -- dict slice for Celery handler registration.
"""

from __future__ import annotations

import logging

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.prepare_options.models import (
    MaturityRequest,
    PrepareOptionsRequestItem,
    PrepareOptionsRequestsInput,
    PrepareOptionsRequestsOutput,
)
from backend.quant.stats.constants import FUTURES_PERIODS

logger = logging.getLogger(__name__)

_TASK_NAME = "prepare_futures_requests"
_CACHE_TTL_SECONDS = 3600

# Mapping from a FUTURES_PERIODS member to the ``period`` label consumed
# by the yfinance fetcher (must be a key in ``_PERIOD_MAP`` in
# ``backend.resources.stats.providers.yfinance.transformer``).
_FETCHER_PERIOD_FOR_MEMBER: dict[str, str] = {
    "ONE_MONTH":   "1mo",
    "ONE_QUARTER": "3mo",
    "HALF_YEAR":   "1y",
    "ONE_YEAR":    "1y",
}


# ---------------------------------------------------------------------------
# Helpers -- used by task_fn + handler so the logic is identical in both
# ---------------------------------------------------------------------------


def _propose_maturities(pipeline: str = "futures") -> list[MaturityRequest]:
    """Return the full catalogue of maturity windows for futures.

    The list is ordered by ascending ``seconds`` so callers can dispatch
    short-dated pipelines first.
    """

    ordered = sorted(FUTURES_PERIODS, key=lambda m: m.seconds)
    proposed: list[MaturityRequest] = []
    for member in ordered:
        proposed.append(
            MaturityRequest(
                label=member.name.lower(),
                display_name=member.display_name,
                seconds=member.seconds,
                pipeline=pipeline,
            )
        )
    return proposed


def _propose_requests(
    symbol: str,
    maturities: list[MaturityRequest],
) -> list[PrepareOptionsRequestItem]:
    """Convert the maturity plan into ``get_and_calculate_stats``-ready items.

    Each item sets ``pipeline='futures'`` and ``maturity_horizon`` equal
    to the window's raw ``seconds``.  The ``period`` label is drawn from
    ``_FETCHER_PERIOD_FOR_MEMBER`` (falls back to ``"1y"`` for any
    unknown member) so the shared fetcher gets a label it recognises.
    """

    items: list[PrepareOptionsRequestItem] = []
    for m in maturities:
        # ``m.label`` is the lower-cased enum member name (e.g.
        # ``"one_month"``).  ``_FETCHER_PERIOD_FOR_MEMBER`` is keyed by
        # the upper-cased enum name.
        enum_name = m.label.upper()
        period_label = _FETCHER_PERIOD_FOR_MEMBER.get(enum_name, "1y")
        items.append(
            PrepareOptionsRequestItem(
                symbol=symbol,
                period=period_label,
                pipeline=m.pipeline,
                maturity_horizon=m.seconds,
                maturity_label=m.label,
                maturity_seconds=m.seconds,
            )
        )
    return items


# ---------------------------------------------------------------------------
# Celery handler -- pure async, runs in the worker.
# ---------------------------------------------------------------------------


async def _prepare_futures_requests_handler(payload: dict) -> dict:
    """Compute the full catalogue of maturities and request items.

    ``maturity_horizon`` is intentionally **not** used here -- it lives
    on the hosting node.  This function emits every window so callers
    can filter them based on their own horizon.

    Args:
        payload: JSON-serialised :class:`PrepareOptionsRequestsInput`.

    Returns:
        JSON dict matching :class:`PrepareOptionsRequestsOutput`.
    """

    inp = PrepareOptionsRequestsInput.model_validate(payload)
    maturities = _propose_maturities(pipeline="futures")
    requests = _propose_requests(inp.stock_symbol, maturities)

    output = PrepareOptionsRequestsOutput(
        maturities=maturities,
        requests=requests,
        source_symbol=inp.stock_symbol,
    )
    return output.model_dump(mode="json")


# ---------------------------------------------------------------------------
# LangGraph layer -- @task orchestration
# ---------------------------------------------------------------------------


async def _prepare_futures_requests_task(
    task_input: TaskInput[PrepareOptionsRequestsInput],
) -> TaskOutput[PrepareOptionsRequestsOutput]:
    """LangGraph @task: delegates proposal to the Celery completion worker.

    Args:
        task_input: Typed envelope with task context + input content.

    Returns:
        Typed output envelope for UI / audit consumption.
    """

    ctx = task_input.ctx
    payload = task_input.content.model_dump(mode="json")

    await create_task(
        ctx.thread_id,
        ctx.node_id,
        ctx.node_name,
        ctx.task_id,
        ctx.task_name,
        payload,
        view_type="Stats",
        stats_views=["Maturities"],
    )

    try:
        result = await delegate_completion(
            ctx.thread_id, ctx.task_id, ctx.node_id, ctx.node_name, ctx.task_name, payload,
        )
        output = PrepareOptionsRequestsOutput.model_validate(result)
        await complete_task(
            ctx.thread_id,
            ctx.node_id,
            ctx.node_name,
            ctx.task_id,
            ctx.task_name,
            output_data=output.model_dump(mode="json"),
            view_type="Stats",
        )
        return TaskOutput(ctx=ctx, content=output)
    except Exception as exc:
        await complete_task(
            ctx.thread_id,
            ctx.node_id,
            ctx.node_name,
            ctx.task_id,
            ctx.task_name,
            failed=True,
            error=str(exc),
        )
        raise


# ---------------------------------------------------------------------------
# NodeTask registration -- exported and referenced by PrepareFuturesNode
# ---------------------------------------------------------------------------


prepare_futures_requests: NodeTask[
    PrepareOptionsRequestsInput,
    PrepareOptionsRequestsOutput,
] = NodeTask(
    name=_TASK_NAME,
    description=(
        "Propose the full catalogue of maturity windows for prepare_futures: "
        "returns an ordered list of MaturityRequest entries plus an equivalent "
        "list of PrepareOptionsRequestItem objects that feed directly into "
        "get_and_calculate_stats (pipeline='futures'). Maturity filtering by "
        "horizon is the caller's responsibility -- it is NOT done in this task."
    ),
    input_type=PrepareOptionsRequestsInput,
    output_type=PrepareOptionsRequestsOutput,
    task_fn=_prepare_futures_requests_task,
    handler=_prepare_futures_requests_handler,
    cache_ttl_seconds=_CACHE_TTL_SECONDS,
)


HANDLERS: dict = {_TASK_NAME: _prepare_futures_requests_handler}


__all__ = [
    "prepare_futures_requests",
    "HANDLERS",
]
