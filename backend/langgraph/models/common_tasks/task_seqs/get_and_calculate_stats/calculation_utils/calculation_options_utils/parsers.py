"""parsers — OSI contract name parsing and value coercion helpers.

Provides:
- ``parse_contract_name``: parse a full OSI option symbol into its components.
- ``_coerce_pct``:         coerce a percent value string/float to a plain float.
- ``_parse_iso_datetime``: best-effort ISO-8601 string to UTC datetime.
- ``_contract_cost``:      representative cost of a contract for breakeven aggregation.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from backend.langgraph.models.common_tasks.errors.codes import (
    DERIV_TASK_CONTRACT_PARSE_WARN,
)
from backend.quant.stats import safe_float

# OSI option symbol: root + YYMMDD + C/P + 8-digit strike (thousandths of a dollar).
_OSI_RE = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")


def parse_contract_name(contract_name: str) -> tuple[str, datetime, str, float]:
    """Parse an OSI option symbol into its components.

    The OSI symbol ``AAPL260601P00250000`` decomposes as
    ``root='AAPL'``, ``YYMMDD='260601'`` (2026-06-01), ``'P'`` (put), and an
    8-digit strike ``00250000`` in thousandths of a dollar (strike ``250.0``).

    Args:
        contract_name: Full OSI contract symbol.

    Returns:
        Tuple ``(root, expiry_date, options_type, strike)`` where ``expiry_date`` is a
        timezone-aware UTC ``datetime`` at midnight, ``options_type`` is ``'call'`` or
        ``'put'``, and ``strike`` is a float.

    Raises:
        ValueError: When *contract_name* is not a valid OSI symbol (carries
            ``DERIV_TASK_CONTRACT_PARSE_WARN``).
    """
    match = _OSI_RE.match(contract_name.strip().upper())
    if match is None:
        raise ValueError(
            f"[{DERIV_TASK_CONTRACT_PARSE_WARN}] cannot parse OSI contract_name "
            f"{contract_name!r}."
        )
    root, ymd, cp, strike_raw = match.groups()
    year, month, day = 2000 + int(ymd[0:2]), int(ymd[2:4]), int(ymd[4:6])
    try:
        expiry_date = datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError(
            f"[{DERIV_TASK_CONTRACT_PARSE_WARN}] invalid expiry date in contract_name "
            f"{contract_name!r}: {exc}."
        ) from exc
    options_type = "call" if cp == "C" else "put"
    strike = int(strike_raw) / 1000.0
    return root, expiry_date, options_type, strike


def _coerce_pct(val: object) -> float | None:
    """Coerce a percent value (``'107.81%'`` or ``107.81``) to a plain float.

    Args:
        val: Raw value, possibly a string with a trailing ``'%'``.

    Returns:
        Float percent (``107.81``) or ``None`` when not numeric.
    """
    if isinstance(val, str):
        val = val.strip().rstrip("%").strip()
    return safe_float(val)


def _parse_iso_datetime(val: object) -> datetime | None:
    """Best-effort parse of an ISO-8601 timestamp into a UTC datetime.

    Args:
        val: Raw value (ISO date/datetime string) or ``None``.

    Returns:
        Timezone-aware UTC ``datetime`` or ``None`` when unparseable.
    """
    if not isinstance(val, str) or not val.strip():
        return None
    text = val.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _contract_cost(bid: float | None, ask: float | None, last_price: float | None) -> float | None:
    """Return the representative cost of a contract for breakeven aggregation.

    Prefers the bid/ask midpoint when both quotes are positive, otherwise the last
    traded price.

    Args:
        bid:        Bid price or ``None``.
        ask:        Ask price or ``None``.
        last_price: Last traded price or ``None``.

    Returns:
        Float cost, or ``None`` when no usable quote is available.
    """
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    if last_price is not None and last_price > 0:
        return last_price
    return None


__all__ = [
    "parse_contract_name",
    "_coerce_pct",
    "_parse_iso_datetime",
    "_contract_cost",
]
