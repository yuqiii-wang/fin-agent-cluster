"""Options-chain stats service.

Dispatches options-chain fetching for a given underlying ticker to one of the
supported providers:

* ``"mock"``     -- in-process mock transport (returns empty).
* ``"yfinance"`` -- pulls the full option chain (every maturity) via
  :func:`~backend.resources.stats.providers.yfinance.fetch_options`.

Callers can route here via :func:`service_for_symbol` with
``force_product="options"``; no ticker-suffix auto-selection routes to this
service because the same underlying ticker (``AAPL``, ...) also validly
refers to the equity itself.  Downstream callers can also inject options
content through ``get_stats(json_input=...)`` separately from this live
fetch path.

Maturity horizon
----------------
The ``maturity_horizon`` argument controls how far out to fetch maturities
for time-bounded products (options, futures, bonds, repo, ...).  It is
forwarded verbatim to the backing provider, so it accepts anything
recognised by that provider: a
:class:`~backend.quant.stats.constants.OPTIONS_PERIODS` member, one
of its ``display_name`` strings (``'next'``, ``'one week'``, ``'one month'``,
``'one quarter'``, ``'half year'``, ``'one year'``), or a raw number of
seconds.  ``None`` (default) maps to ``OPTIONS_PERIODS.ONE_YEAR``.

Contract
--------
Callers invoke :func:`list_stats` and :func:`get_stats` without knowing
which provider is backing them.  The provider label is chosen upstream in
:class:`~backend.resources.stats.client.StatsClient`.
"""

from __future__ import annotations

import logging

from _shared.httpx_client import AsyncClient
from backend.quant.stats.constants import OPTIONS_PERIODS
from backend.resources.stats.models import StatsListResponse, StatsRecord

logger = logging.getLogger(__name__)


SUPPORTED_PROVIDERS = frozenset({"mock", "yfinance"})


def supports_provider(provider: str) -> bool:
    """Return ``True`` when *provider* is supported for options."""
    return provider in SUPPORTED_PROVIDERS


async def list_stats(
    symbol: str,
    period: str | None,
    provider: str,
    http: AsyncClient | None,
    *,
    limit: int = 1,
    maturity_horizon: OPTIONS_PERIODS | str | int | float | None = None,
) -> StatsListResponse:
    """Options-chain fetch.

    For ``yfinance``, pulls the full option chain (only maturities within
    ``maturity_horizon`` from ``now``).  ``limit`` is ignored; a single
    chain record is returned.  ``period`` (the legacy string label) is
    forwarded to ``maturity_horizon`` when no explicit horizon is supplied,
    so callers that previously used ``"1y"`` still work.

    For unknown providers returns an empty list.
    """
    logger.debug(
        "options.list_stats: symbol=%s period=%s provider=%s",
        symbol, period, provider,
    )
    if provider == "yfinance":
        return await _list_yfinance(
            symbol,
            maturity_horizon=_pick_horizon(maturity_horizon, period),
        )
    if provider == "mock":
        return StatsListResponse(items=[], total=0)
    logger.warning("options.list_stats: unknown provider=%r returning empty", provider)
    return StatsListResponse(items=[], total=0)


async def get_stats(
    record_id: str,
    provider: str,
    http: AsyncClient | None,
    *,
    maturity_horizon: OPTIONS_PERIODS | str | int | float | None = None,
) -> StatsRecord | None:
    """Options-chain fetch by record id.

    ``record_id`` is expected to be of the form
    ``yf-<symbol>-options-<seconds>`` when ``provider == "yfinance"``; the
    trailing seconds are a maturity-horizon hint but callers can also
    supply ``maturity_horizon`` to override.
    """
    logger.debug("options.get_stats: id=%s provider=%s", record_id, provider)
    if provider == "yfinance":
        return await _get_yfinance(record_id, maturity_horizon=maturity_horizon)
    return None


# ---------------------------------------------------------------------------
# Provider helpers
# ---------------------------------------------------------------------------


def _pick_horizon(
    explicit: OPTIONS_PERIODS | str | int | float | None,
    period_fallback: str | None,
) -> OPTIONS_PERIODS | str | int | float | None:
    """Resolve the effective horizon from (explicit, period).

    ``explicit`` wins when it is not ``None``; otherwise the legacy
    ``period`` string is forwarded to the fetcher (which knows how to map
    it to a ``OPTIONS_PERIODS`` member or to a raw number of
    seconds).
    """
    if explicit is not None:
        return explicit
    return period_fallback


async def _list_yfinance(
    symbol: str,
    *,
    maturity_horizon: OPTIONS_PERIODS | str | int | float | None,
) -> StatsListResponse:
    from backend.resources.stats.providers.yfinance.fetch_options import fetch_options

    if not symbol:
        return StatsListResponse(items=[], total=0)
    try:
        record = await fetch_options(symbol, maturity_horizon=maturity_horizon)
    except Exception as exc:
        logger.warning("options yfinance fetch failed symbol=%r: %s", symbol, exc)
        return StatsListResponse(items=[], total=0)
    return StatsListResponse(items=[record], total=1)


async def _get_yfinance(
    record_id: str,
    *,
    maturity_horizon: OPTIONS_PERIODS | str | int | float | None,
) -> StatsRecord | None:
    from backend.resources.stats.providers.yfinance.fetch_options import fetch_options

    # Accept either the old-style "yf-<symbol>-options" or the new
    # "yf-<symbol>-options-<seconds>" id format; either way, the leading
    # part gives us the symbol and the trailing seconds part is only a
    # hint.
    parts = record_id.split("-")
    if len(parts) < 3 or parts[0] != "yf" or parts[2] != "options":
        logger.debug("options.get_stats yfinance: unrecognised id %r", record_id)
        return None
    symbol = parts[1]
    try:
        return await fetch_options(symbol, maturity_horizon=maturity_horizon)
    except Exception as exc:
        logger.warning("options.get_stats yfinance id=%r: %s", record_id, exc)
        return None


__all__ = ["list_stats", "get_stats", "supports_provider", "OPTIONS_PERIODS"]
