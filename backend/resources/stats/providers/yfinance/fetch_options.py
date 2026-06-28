"""yfinance options-chain fetcher.

Pulls the option chain for a given underlying ticker via
:func:`yfinance.Ticker.option_chain`, and packages the ``(calls, puts)``
pairs into a :class:`~backend.resources.stats.models.StatsRecord` shaped
the way the rest of the codebase expects (see the
``calculation_options_utils`` handler in
``backend.langgraph.models.common_tasks...``).

Maturity horizon
----------------
The ``maturity_horizon`` argument controls the furthest expiry fetched.
It is intentionally generic: the same type is used for any time-bounded
product (options, futures, bonds, repo, ...), even though only the
options-chain use-case is implemented here today.

Accepted values:

* A :class:`~backend.quant.stats.constants.OPTIONS_PERIODS` enum
  member (preferred).  Defaults to ``OPTIONS_PERIODS.ONE_YEAR``.
* One of its ``display_name`` strings: ``'next'``, ``'one week'``,
  ``'one month'``, ``'one quarter'``, ``'half year'``, ``'one year'``.
* A plain ``int`` / ``float`` number of seconds.

Expiries returned by yfinance whose date is strictly later than
``now + horizon_seconds`` are dropped.  If no maturities fall within the
horizon, the fetcher returns an empty record (so the downstream pipeline
still runs cleanly).

yfinance columns / row shape
----------------------------
``option_chain(expiration)`` returns a named tuple ``(calls, puts)``.
Each DataFrame exposes columns listed below; these are renamed to
snake_case before serialising into ``StatsRecord.content``:

* ``contractSymbol``  -> ``contract_name``
* ``strike``           -> ``strike``
* ``lastPrice``        -> ``last_price``
* ``bid``              -> ``bid``
* ``ask``              -> ``ask``
* ``change``           -> ``change``
* ``percentChange``    -> ``percent_change``
* ``volume``           -> ``volume``
* ``openInterest``    -> ``open_interest``
* ``impliedVolatility``-> ``implied_volatility``
* ``lastTradeDate``    -> ``last_trade_date`` (ISO-8601)
* ``currency``         -> ``currency``

Each row additionally carries a string ``expiry`` copied from the
maturity-date string.

Public API
----------
fetch_options(symbol, maturity_horizon=None) -> StatsRecord
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from functools import partial
from typing import Any

import pandas as pd
import yfinance as yf

from backend.quant.stats.constants import OPTIONS_PERIODS
from backend.resources.stats.models import StatsRecord

logger = logging.getLogger(__name__)


# Column mapping: yfinance camelCase column -> output snake_case contract key
_COLUMN_MAP: dict[str, str] = {
    "contractSymbol": "contract_name",
    "strike": "strike",
    "lastPrice": "last_price",
    "bid": "bid",
    "ask": "ask",
    "change": "change",
    "percentChange": "percent_change",
    "volume": "volume",
    "openInterest": "open_interest",
    "impliedVolatility": "implied_volatility",
    "lastTradeDate": "last_trade_date",
    "currency": "currency",
}


async def fetch_options(
    symbol: str,
    maturity_horizon: OPTIONS_PERIODS | str | int | float | None = None,
) -> StatsRecord:
    """Download the option chain for ``symbol`` within the given horizon.

    Runs the blocking ``yf.Ticker.option_chain(...)`` calls in a thread-pool
    executor so the FastAPI event loop is never blocked.

    Args:
        symbol:            Equity ticker, e.g. ``"AAPL"``.
        maturity_horizon:     How far out to pull maturities.  The type is kept
                             generic so it can be reused for other
                             time-bounded products (options, futures, bonds,
                             repo, ...).  Accepts a :class:`OPTIONS_PERIODS`
                             member, one of its ``display_name``
                             strings, or a raw number of seconds.
                             ``None`` (default) maps to
                             ``OPTIONS_PERIODS.ONE_YEAR``.

    Returns:
        :class:`~backend.resources.stats.models.StatsRecord` with
        ``id`` of the form ``"yf-<symbol>-options-<label>`` (e.g.
        ``yf-aapl-options-next``, ``yf-aapl-options-1w``, ``yf-aapl-options-1y``).
        ``content`` exposes ``calls``, ``puts``, ``maturities``,
        ``maturity_horizon_seconds`` and ``maturity_horizon_label``.
    """
    horizon_label, horizon_seconds = _horizon_label_and_seconds(maturity_horizon)
    logger.info(
        "yfinance.fetch_options symbol=%s horizon=%s horizon_seconds=%d",
        symbol, horizon_label, horizon_seconds,
    )

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            partial(_download_options, symbol, horizon_seconds),
        )
    except Exception as exc:
        logger.error(
            "yfinance.fetch_options error symbol=%s error=%s",
            symbol, exc,
        )
        raise

    calls: list[dict] = result["calls"]
    puts: list[dict] = result["puts"]
    maturities: list[str] = result["maturities"]

    record = StatsRecord(
        id=_record_id(symbol, horizon_label),
        symbol=symbol.upper(),
        period="options",
        content={
            "calls": calls,
            "puts": puts,
            "maturities": maturities,
            "maturity_horizon_seconds": horizon_seconds,
            "maturity_horizon_label": horizon_label,
        },
    )

    logger.info(
        "yfinance.fetch_options ok symbol=%s horizon=%s maturities=%d calls=%d puts=%d",
        symbol, horizon_label, len(maturities), len(calls), len(puts),
    )
    return record


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Helpers for recording the horizon in a friendly id string.
# Mapping from OPTIONS_PERIODS member name (lowercased) to the
# short suffix used in StatsRecord.id / cache key.
_HORIZON_LABELS: dict[str, str] = {
    "next": "next",
    "one_week": "1w",
    "one_month": "1mo",
    "one_quarter": "1q",
    "half_year": "6m",
    "one_year": "1y",
}


def _horizon_label_and_seconds(
    value: OPTIONS_PERIODS | str | int | float | None,
) -> tuple[str, int]:
    """Return a ``(label, seconds)`` pair for the given horizon input.

    ``None`` maps to ``OPTIONS_PERIODS.ONE_YEAR``. Values that do not
    match an enum member exactly are snapped to the member with the largest
    ``seconds`` that is still <= ``value``; if no member matches at all the
    raw seconds value is used for the label (``"{seconds}s"``).
    """

    if isinstance(value, OPTIONS_PERIODS):
        return _HORIZON_LABELS.get(value.name.lower(), f"{int(value.seconds)}s"), int(value.seconds)

    if value is None:
        member = OPTIONS_PERIODS.ONE_YEAR
        return _HORIZON_LABELS[member.name.lower()], int(member.seconds)

    if isinstance(value, str):
        key = value.strip().lower().replace("_", " ")
        if not key:
            member = OPTIONS_PERIODS.ONE_YEAR
            return _HORIZON_LABELS[member.name.lower()], int(member.seconds)
        # Try by display name and then by enum name
        for member in OPTIONS_PERIODS:
            if member.display_name.lower() == key or member.name.lower() == key:
                return _HORIZON_LABELS[member.name.lower()], int(member.seconds)
        # Try to parse as seconds int
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
    """Pick the ``OPTIONS_PERIODS`` member whose seconds are the largest
    value still <= ``seconds`` and return ``(label, member_seconds)``. Falls
    back to ``("{seconds}s", seconds)`` when even ``ONE_YEAR`` is too short.
    """

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


def _expiry_within_horizon(expiry: str, horizon_seconds: int, now_utc: datetime) -> bool:
    """Return ``True`` when ``expiry`` (``YYYY-MM-DD``) is at most ``horizon_seconds`` ahead of ``now``."""
    try:
        expiry_dt = datetime.strptime(expiry, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        # yfinance should always return ISO dates; if not, keep it rather
        # than silently drop a maturity the caller explicitly wanted.
        return True
    return (expiry_dt - now_utc).total_seconds() <= horizon_seconds


# ---------------------------------------------------------------------------
# Sync helpers -- run inside executor
# ---------------------------------------------------------------------------


def _download_options(symbol: str, horizon_seconds: int) -> dict:
    """Blocking yfinance option-chain download.

    Iterates over all maturities reported by ``yf.Ticker.options`` and
    pulls the call / put tables for each one that falls within
    ``horizon_seconds`` from now.

    Returns:
        Dict with keys ``calls``, ``puts``, ``maturities``.
    """
    ticker = yf.Ticker(symbol)

    # ``options`` is a tuple of expiry-date strings (``"YYYY-MM-DD"``).
    try:
        raw_maturities: tuple[str, ...] = tuple(ticker.options)
    except Exception:
        raw_maturities = ()

    if not raw_maturities:
        logger.warning(
            "yfinance.fetch_options no maturities for symbol=%s", symbol,
        )
        return {"calls": [], "puts": [], "maturities": []}

    now_utc = datetime.now(tz=timezone.utc)
    maturities = [
        expiry
        for expiry in raw_maturities
        if _expiry_within_horizon(expiry, horizon_seconds, now_utc)
    ]

    dropped = len(raw_maturities) - len(maturities)
    if dropped:
        logger.info(
            "yfinance.fetch_options dropped %d expiry(ies) beyond %d seconds for symbol=%s",
            dropped, horizon_seconds, symbol,
        )

    if not maturities:
        logger.warning(
            "yfinance.fetch_options no maturities within horizon for symbol=%s",
            symbol,
        )
        return {"calls": [], "puts": [], "maturities": []}

    all_calls: list[dict] = []
    all_puts: list[dict] = []

    for expiry in maturities:
        try:
            chain = ticker.option_chain(expiry)
        except Exception as exc:
            logger.warning(
                "yfinance.fetch_options skip expiry=%s symbol=%s: %s",
                expiry, symbol, exc,
            )
            continue

        calls_df = chain.calls if chain.calls is not None else pd.DataFrame()
        puts_df = chain.puts if chain.puts is not None else pd.DataFrame()

        all_calls.extend(_rows_from_df(calls_df, expiry))
        all_puts.extend(_rows_from_df(puts_df, expiry))

    return {
        "calls": all_calls,
        "puts": all_puts,
        "maturities": list(maturities),
    }


def _rows_from_df(df: Any, expiry: str) -> list[dict]:
    """Convert a yfinance calls/puts DataFrame into a list of contract dicts.

    Unknown columns are dropped. Columns are renamed via ``_COLUMN_MAP`` and
    NaN values are coerced to ``None`` so downstream JSON serialiser stays
    happy.  A synthetic ``expiry`` field is attached to every row.
    """
    if df is None:
        return []
    try:
        if df.empty:
            return []
    except AttributeError:
        return []

    # Keep only columns we know about, in a stable order.
    available = [col for col in _COLUMN_MAP if col in getattr(df, "columns", [])]
    subset = df[available].copy()
    subset = subset.rename(columns=_COLUMN_MAP)

    # Convert any ``Timestamp`` / ``datetime`` columns to ISO strings so the
    # Pydantic record is JSON-serialisable.
    for col in list(subset.columns):
        try:
            if pd.api.types.is_datetime64_any_dtype(subset[col]):
                subset[col] = subset[col].apply(_fmt_timestamp)
        except Exception:
            continue

    # Replace NaN/NaT with None for JSON safety.
    subset = subset.replace({float("nan"): None})

    rows: list[dict] = subset.to_dict(orient="records")

    # Make sure contract_name is always a plain string and attach the expiry
    # as a separate convenience field for downstream consumers.
    for row in rows:
        cn = row.get("contract_name")
        if cn is not None:
            row["contract_name"] = str(cn).strip().upper()
        row.setdefault("expiry", expiry)

    return rows


def _fmt_timestamp(value: Any) -> str | None:
    """Best-effort formatting of a pandas Timestamp cell to an ISO-8601 string."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return pd.Timestamp(value).isoformat()
    except Exception:
        return None


def _record_id(symbol: str, horizon_label: str) -> str:
    """Deterministic record id: ``yf-<symbol>-options-<label>``.

    ``label`` is the friendly short form of the maturity horizon
    (``next``, ``1w``, ``1mo``, ``1q``, ``6m``, ``1y``, or ``{seconds}s``
    for a raw custom seconds value).  Example: ``yf-aapl-options-next``
    or ``yf-aapl-options-1y``.
    """

    return f"yf-{symbol.lower()}-options-{horizon_label}"


__all__ = ["fetch_options", "OPTIONS_PERIODS"]
