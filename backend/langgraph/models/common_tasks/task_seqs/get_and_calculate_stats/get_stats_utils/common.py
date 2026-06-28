"""common -- shared constants, helpers, and models for get_stats product handlers.

Centralises the pieces used by both OHLCV and options fetch pipelines:

* ``PERIOD_FALLBACKS`` -- period roll-down table for OHLCV fetching.
* ``_HORIZON_LABELS`` -- short cache/tag labels for options maturities.
* :func:`_horizon_label_and_seconds` / :func:`_snap_seconds_to_label` -- horizon
  value normalisation used by the options cache-key logic.
* :func:`_build_provider_chain` -- provider fallback list (honours FMP API key
  availability so disabled providers are skipped).
* :func:`_make_cache_key` -- deterministic SHA-256 cache key builder used by
  both :mod:`get_ohlcv_stats` and :mod:`get_options_stats`.
* :func:`_persist` / :func:`_detect_pipeline` / :func:`_build_stats_record` --
  raw-payload persister and the JSON-injection helpers that build a
  ``StatsRecord`` from an upstream dict.

Public exports (only from submodules)
-------------------------------------
``GetStatsInput``  -- shared input model (imported from :mod:`.models`).
``GetStatsOutput`` -- shared output model (imported from :mod:`.models`).
"""

from __future__ import annotations

import hashlib
import json
import logging

from backend.config import get_settings
from backend.db.postgres import raw_conn
from backend.db.postgres.queries.fin_markets_input_raw import InputRawSQL
from backend.langgraph.models.common_tasks.errors.codes import (
    STATS_TASK_PERIOD_FALLBACK,
    STATS_TASK_PROVIDER_ERROR,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils.models import (
    GetStatsInput,
    GetStatsOutput,
)
from backend.quant.stats import STATS_DATA_TYPE
from backend.quant.stats.constants import OPTIONS_PERIODS
from backend.resources.stats.models import StatsRecord
from backend.resources.stats.routing import provider_for_symbol

logger = logging.getLogger(__name__)

_TASK_NAME = "get_stats"
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

# Short label used in cache keys / record ids for options-chain fetches.
# Mirrors backend.resources.stats.providers.yfinance.fetch_options's
# mapping so the two modules stay in sync without forcing the Celery
# worker to import yfinance at module-import time.
_HORIZON_LABELS: dict[str, str] = {
    "next": "next",
    "one_week": "1w",
    "one_month": "1mo",
    "one_quarter": "1q",
    "half_year": "6m",
    "one_year": "1y",
}


def _horizon_label_and_seconds(value: object) -> tuple[str, int]:
    """Translate ``maturity_horizon`` inputs into a ``(label, seconds)`` pair.

    ``None`` → ``OPTIONS_PERIODS.ONE_YEAR``.
    """

    if isinstance(value, OPTIONS_PERIODS):
        return (
            _HORIZON_LABELS.get(
                value.name.lower(), f"{int(value.seconds)}s"
            ),
            int(value.seconds),
        )

    if value is None:
        member = OPTIONS_PERIODS.ONE_YEAR
        return _HORIZON_LABELS[member.name.lower()], int(member.seconds)

    if isinstance(value, str):
        key = value.strip().lower().replace("_", " ")
        if not key:
            member = OPTIONS_PERIODS.ONE_YEAR
            return _HORIZON_LABELS[member.name.lower()], int(member.seconds)
        for member in OPTIONS_PERIODS:
            if member.display_name.lower() == key or member.name.lower() == key:
                return (
                    _HORIZON_LABELS.get(
                        member.name.lower(),
                        f"{int(member.seconds)}s"
                    ),
                    int(member.seconds),
                )
        try:
            seconds = int(float(key))
        except ValueError as exc:
            raise ValueError(
                f"maturity_horizon string {value!r} is not a recognised "
                f"OPTIONS_PERIODS label."
            ) from exc
        if seconds < 0:
            raise ValueError(f"maturity_horizon seconds must be >= 0, got {value}")
        return _snap_seconds_to_label(seconds)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = int(value)
        if seconds < 0:
            raise ValueError(f"maturity_horizon seconds must be >= 0, got {value}")
        return _snap_seconds_to_label(seconds)

    if isinstance(value, (tuple, list)) and len(value) == 2:
        try:
            seconds = int(value[1])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"maturity_horizon tuple[1] is not an int seconds value: {value}"
            ) from exc
        if seconds < 0:
            raise ValueError(f"maturity_horizon seconds must be >= 0, got {value}")
        return _snap_seconds_to_label(seconds)

    raise ValueError(f"Unsupported maturity_horizon value: {value!r}")


def _snap_seconds_to_label(seconds: int) -> tuple[str, int]:
    """Pick the enum member with the largest ``seconds`` still <= ``seconds``."""
    ordered = sorted(OPTIONS_PERIODS, key=lambda m: m.seconds)
    chosen_label = f"{seconds}s"
    chosen_seconds = seconds
    for member in ordered:
        if member.seconds <= seconds:
            chosen_label = _HORIZON_LABELS.get(
                member.name.lower(), f"{int(member.seconds)}s"
            )
            chosen_seconds = int(member.seconds)
        else:
            break
    return chosen_label, chosen_seconds


# Provider fallback chains: when the primary provider yields no data, try the
# next provider in the chain.  Used as the default matrix when
# ``symbol_config.provider_preference_for_symbol`` does not return a
# product-specific ordered preference list.
_PROVIDER_FALLBACK_CHAINS: dict[str, list[str]] = {
    "fmp":      ["fmp", "yfinance"],
    "yfinance": ["yfinance", "fmp"],
    "mock":     ["mock", "yfinance"],
    "akshare":  ["yfinance", "fmp"],
}


def _build_provider_chain(symbol: str) -> list[str]:
    """Return the ordered provider list for stats fetching.

    Provider priority (highest → lowest):
      1. Per-symbol provider preferences from
         :func:`backend.resources.stats.symbol_config.provider_preference_for_symbol`
         (product-aware: futures / crypto spot / macro FX-yields / index tickers
         all carry explicit, ordered provider lists so they never accidentally
         hit a provider with zero coverage for that asset class).
      2. Fallback to :func:`provider_for_symbol` (index-driven cache lookup keyed
         off ticker suffix → yf_exchange → market_indexes.stats_provider).
      3. Final fallback: ``Settings.STATS_PROVIDER`` or ``mock``, resolved via
         the static ``_PROVIDER_FALLBACK_CHAINS`` matrix.

    ``"fmp"`` is unconditionally stripped when ``Settings.FMP_API_KEY`` is not
    set, so providers that only exist on FMP fall through cleanly to the next
    candidate.

    Args:
        symbol: Normalised (uppercase) ticker symbol.

    Returns:
        Non-empty list of provider labels in priority order.
    """

    from backend.resources.stats.symbol_config import (
        provider_preference_for_symbol as _sym_provider_prefs,
    )

    settings = get_settings()
    fmp_key_ok = bool(settings.FMP_API_KEY)

    per_symbol_chain = _sym_provider_prefs(symbol)
    if per_symbol_chain:
        seen: set[str] = set()
        ordered: list[str] = []
        for p in per_symbol_chain:
            if p == "fmp" and not fmp_key_ok:
                continue
            if p not in seen:
                seen.add(p)
                ordered.append(p)
        if ordered:
            return ordered

    primary = provider_for_symbol(symbol) or (settings.STATS_PROVIDER or "mock").strip().lower()
    chain = list(_PROVIDER_FALLBACK_CHAINS.get(primary, [primary]))
    if not fmp_key_ok:
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
                "common_tasks/get_stats",
                symbol,
                source,
                method,
                cache_key,
                ttl_seconds,
                json.dumps(input_payload),
                json.dumps(output_payload),
            ),
        )


def _detect_pipeline(payload: object) -> str:
    """Infer the pipeline label from an injected ``json_input`` payload.

    Rules:
      * dict containing ``'calls'`` or ``'puts'`` -> ``'options'``
      * otherwise -> ``'ohlcv'`` (including bare OHLCV matrix or full ``StatsRecord``)
    """
    if isinstance(payload, dict):
        content = payload.get("content")
        probe = content if isinstance(content, dict) else payload
        if isinstance(probe, dict) and (
            isinstance(probe.get("calls"), list) or isinstance(probe.get("puts"), list)
        ):
            return STATS_DATA_TYPE.OPTIONS.value
    return STATS_DATA_TYPE.OHLCV.value


def _build_stats_record(symbol: str, period: str, json_input: dict) -> StatsRecord:
    """Build a :class:`StatsRecord` from injected JSON.

    Accepts either a full ``StatsRecord`` dict (contains a ``content`` key, whose
    value is taken verbatim) or a bare payload dict (used as ``content`` directly).

    The record ``id`` carries the pipeline label but does not affect routing.
    """
    pipeline = _detect_pipeline(json_input)
    if isinstance(json_input, dict) and "content" in json_input and isinstance(json_input["content"], dict):
        return StatsRecord(
            id=str(json_input.get("id") or f"json-{symbol.lower()}-{pipeline}-{period}"),
            symbol=str(json_input.get("symbol") or symbol),
            period=str(json_input.get("period") or period),
            content=json_input["content"],
        )
    return StatsRecord(
        id=f"json-{symbol.lower()}-{pipeline}-{period}",
        symbol=symbol,
        period=period,
        content=json_input,
    )


def _log_period_fallback(symbol: str, provider: str, period: str) -> None:
    logger.error(
        "[%s] symbol=%s provider=%s period fallback %s yielded no bars",
        STATS_TASK_PERIOD_FALLBACK, symbol, provider, period,
    )


def _log_provider_error(symbol: str, provider: str, period: str, exc: Exception) -> None:
    logger.error(
        "[%s] symbol=%s provider=%s period=%s error=%s",
        STATS_TASK_PROVIDER_ERROR, symbol, provider, period, exc,
    )


__all__ = [
    "_TASK_NAME",
    "_METHOD",
    "PERIOD_FALLBACKS",
    "_build_provider_chain",
    "_make_cache_key",
    "_horizon_label_and_seconds",
    "_snap_seconds_to_label",
    "_persist",
    "_detect_pipeline",
    "_build_stats_record",
    "_log_period_fallback",
    "_log_provider_error",
    "GetStatsInput",
    "GetStatsOutput",
]
