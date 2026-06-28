"""Unified symbol configuration for the stats resource layer.

This module is the **single source of truth** for:

1. Product-type detection (``stock`` / ``index`` / ``futures`` / ``options`` /
   ``macro`` / ``crypto``) from a ticker symbol.
2. Per-provider symbol support — which provider(s) natively handle a given
   symbol, and in what priority order.
3. Per-product provider preference — e.g. crypto spot tickers (``BTC-USD``)
   should prefer ``yfinance`` over ``fmp``/``mock`` regardless of
   ``Settings.STATS_PROVIDER`` since mock has zero crypto data and FMP's
   crypto coverage is spotty.

All callers (``StatsClient``, ``service_for_symbol``, ``get_stats_utils``,
``provider_for_symbol``) should use the helpers exported here instead of
defining their own ad-hoc ``*_symbol`` heuristics.  LangGraph / task
orchestration code must NOT define its own symbol-pattern logic — it
should delegate to this resource-level module.

Public exports
--------------
``detect_product_type`` — returns one of the ``PRODUCT_*`` labels.
``provider_preference_for_symbol`` — returns ordered list of provider labels
  that are known to natively support the given symbol, highest-priority first.
``is_product`` — thin predicate wrapper, e.g. ``is_product("CL=F", "futures")``.
``PRODUCT_STOCK / PRODUCT_INDEX / PRODUCT_FUTURES / PRODUCT_OPTIONS /
  PRODUCT_MACRO / PRODUCT_CRYPTO`` — product label constants (for symmetry
  with ``services.routing``; they're re-exported from there for convenience).
"""

from __future__ import annotations

import re
from typing import Callable

from backend.resources.stats.services.routing import (
    PRODUCT_INDEX,
    PRODUCT_OPTIONS,
    PRODUCT_STOCK,
    PRODUCT_FUTURES,
    PRODUCT_MACRO,
)

PRODUCT_CRYPTO = "crypto"

_ALL_PRODUCT_LABELS = frozenset(
    {PRODUCT_STOCK, PRODUCT_INDEX, PRODUCT_FUTURES,
     PRODUCT_OPTIONS, PRODUCT_MACRO, PRODUCT_CRYPTO}
)


# ---------------------------------------------------------------------------
# 1. Explicit symbol registries (higher priority than pattern matching)
# ---------------------------------------------------------------------------

_CRYPTO_SPOT_SYMBOLS: frozenset[str] = frozenset({
    "BTC-USD",
    "ETH-USD",
})

_PRECIOUS_METAL_FUTURES: frozenset[str] = frozenset({
    "GC=F",   # Gold
    "SI=F",   # Silver
})

_COMMODITY_FUTURES: frozenset[str] = frozenset({
    "NG=F",   # Natural Gas
    "CL=F",   # Crude Oil (WTI)
})

_RATES_FUTURES: frozenset[str] = frozenset({
    "SR3=F",  # SOFR 3-Month Futures
    "ES=F",   # S&P 500 E-mini
    "YM=F",   # Dow E-mini
    "NQ=F",   # Nasdaq 100 E-mini
})

_FUTURES_EXPLICIT: frozenset[str] = (
    _PRECIOUS_METAL_FUTURES
    | _COMMODITY_FUTURES
    | _RATES_FUTURES
)


# ---------------------------------------------------------------------------
# 2. Pattern predicates (lower priority; used as fallback after registries)
# ---------------------------------------------------------------------------

def _has_suffix(symbol: str, suffix: str) -> bool:
    return symbol.upper().endswith(suffix.upper())


def _has_prefix(symbol: str, prefix: str) -> bool:
    return symbol.upper().startswith(prefix.upper())


def _matches_any(symbol: str, patterns: tuple[str, ...]) -> bool:
    up = symbol.upper()
    return any(
        (p.endswith("$") and up.endswith(p[:-1]))
        or (p.startswith("^") and up.startswith(p[1:]))
        or (p == up)
        for p in patterns
    )


# Crypto spot pattern: yfinance convention "<BASE>-<QUOTE>" for major pairs.
# Examples: BTC-USD, ETH-USD, SOL-USD, BNB-EUR ...
_CRYPTO_SPOT_RE = re.compile(r"^[A-Z0-9]{2,10}-(USD|EUR|GBP|JPY|USDT|USDC|BTC|ETH)$")

# Macro FX / yield pattern: yfinance convention "XXXYYY=X" for FX pairs and
# tickers like ^TNX (10Y Treasury yield), ^FVX (5Y), ^TYX (30Y).
_MACRO_FX_SUFFIX = "=X"
_MACRO_YIELD_PREFIX = "^T"


# ---------------------------------------------------------------------------
# 3. Product-type detection (single source of truth)
# ---------------------------------------------------------------------------

# Ordered list of detectors: first match wins.
# Each entry is (product_label, predicate).
_PRODUCT_DETECTORS: list[tuple[str, Callable[[str, dict[str, bool]], bool]]] = [
    (
        PRODUCT_INDEX,
        lambda s, ctx: ctx.get("is_index", False) or s.startswith("^"),
    ),
    (
        PRODUCT_FUTURES,
        lambda s, ctx: s in _FUTURES_EXPLICIT or _has_suffix(s, "=F"),
    ),
    (
        PRODUCT_CRYPTO,
        lambda s, ctx: s in _CRYPTO_SPOT_SYMBOLS or bool(_CRYPTO_SPOT_RE.match(s)),
    ),
    (
        PRODUCT_MACRO,
        lambda s, ctx: (
            _has_suffix(s, _MACRO_FX_SUFFIX)
            or (_has_prefix(s, _MACRO_YIELD_PREFIX) and s.startswith("^"))
        ),
    ),
]


def detect_product_type(
    symbol: str | None,
    *,
    is_index: bool = False,
) -> str:
    """Determine the stats *product type* for *symbol*.

    Resolution order (highest → lowest):
      1. ``is_index=True`` **or** leading ``^`` → ``PRODUCT_INDEX``.
      2. Explicit futures registry **or** ``=F`` suffix → ``PRODUCT_FUTURES``.
      3. Explicit crypto registry **or** ``<BASE>-<QUOTE>` pattern →
         ``PRODUCT_CRYPTO``.
      4. ``=X`` FX suffix **or** ``^TNX``-style yield prefix → ``PRODUCT_MACRO``.
      5. Everything else → ``PRODUCT_STOCK`` (safe catch-all).

    ``PRODUCT_CRYPTO`` callers route through the regular *stock* service at
    the transport level (they are structurally OHLCV) but keep the
    ``crypto`` label for downstream quant_stats instrument_type assignment
    and viewer rendering.

    Args:
        symbol:   Ticker symbol (case-insensitive). ``None`` / ``""`` falls
                  back to ``PRODUCT_STOCK``.
        is_index: Pass ``True`` when the DB-backed ``is_index_ticker()`` has
                  already classified this symbol as an index.  Bypasses all
                  heuristics and returns ``PRODUCT_INDEX`` immediately.

    Returns:
        One of the ``PRODUCT_*`` constants.
    """

    if not symbol:
        return PRODUCT_STOCK
    sym = symbol.upper()
    ctx: dict[str, bool] = {"is_index": bool(is_index)}
    for label, pred in _PRODUCT_DETECTORS:
        try:
            if pred(sym, ctx):
                return label
        except Exception:
            continue
    return PRODUCT_STOCK


def is_product(symbol: str | None, product_label: str, **kwargs: bool) -> bool:
    """Predicate: is *symbol* classified as *product_label*?

    Thin wrapper around :func:`detect_product_type`.
    """

    if product_label not in _ALL_PRODUCT_LABELS:
        return False
    return detect_product_type(symbol, **kwargs) == product_label


# ---------------------------------------------------------------------------
# 4. Per-provider symbol support (used by provider_for_symbol + fallback
#    chains to short-circuit bad providers before they 404).
# ---------------------------------------------------------------------------

# Providers that have ZERO support for a given product type — they will
# *always* fail for those symbols, so we never even try them.
_PROVIDER_PRODUCT_BLOCKLIST: dict[str, frozenset[str]] = {
    # akshare is for Chinese A-shares only — no futures/crypto/FX at all.
    "akshare": frozenset({PRODUCT_FUTURES, PRODUCT_CRYPTO, PRODUCT_MACRO,
                          PRODUCT_INDEX}),
    # mock provider has no crypto/futures/index data as of MOCK_STATS content.
    "mock":    frozenset({PRODUCT_CRYPTO, PRODUCT_FUTURES}),
}

# Per-product provider *preference* order.  When a symbol is detected as
# product X, we prepend these providers (in order) to whatever the global
# Settings-driven chain would have been, skipping any that are blocked
# (missing API key, on the blocklist above).
_PRODUCT_PROVIDER_PREFERENCE: dict[str, list[str]] = {
    # Crypto spot: yfinance has excellent coverage; FMP is unreliable; mock
    # has zero crypto rows.  Always go yfinance first.
    PRODUCT_CRYPTO:  ["yfinance", "fmp"],
    # Futures: yfinance "max" period works reliably for the explicit =F
    # registry; FMP also has futures but yfinance's is more complete.
    PRODUCT_FUTURES: ["yfinance", "fmp"],
    # Macro (FX / yields): yfinance primary; FMP secondary (limited yield
    # data but OK for FX).  akshare is blocklisted for this product.
    PRODUCT_MACRO:   ["yfinance", "fmp"],
    # Indexes: yfinance has global coverage; FMP has US + a subset of global.
    PRODUCT_INDEX:   ["yfinance", "fmp"],
}

# FMP is a REST provider.  When FMP_API_KEY is not set, the upstream caller
# (StatsClient / _build_provider_chain) strips it.  We don't duplicate that
# check here — the preference order is "best-guess when FMP IS available".


def provider_preference_for_symbol(symbol: str | None, *, is_index: bool = False) -> list[str]:
    """Return an *ordered* list of providers that are a good fit for *symbol*.

    Returns providers from best → worst match based on the detected product
    type and the explicit per-product preference + per-provider blocklists.
    The caller (``provider_for_symbol`` / ``_build_provider_chain``) is
    responsible for trimming FMP when ``FMP_API_KEY`` is missing, and for
    appending ``Settings.STATS_PROVIDER`` as a last-resort fallback when
    this preference list alone is empty.

    Args:
        symbol:   Ticker symbol (case-insensitive).
        is_index: Forwarded to :func:`detect_product_type`.

    Returns:
        List of provider labels.  May be empty when *symbol* is ``None`` /
        falls into ``PRODUCT_STOCK`` with no explicit preference (callers
        should then use the global default chain).
    """

    product = detect_product_type(symbol, is_index=is_index)
    blocked: set[str] = set()
    for prov, blocked_products in _PROVIDER_PRODUCT_BLOCKLIST.items():
        if product in blocked_products:
            blocked.add(prov)
    pref = _PRODUCT_PROVIDER_PREFERENCE.get(product, [])
    return [p for p in pref if p not in blocked]


__all__ = [
    "PRODUCT_STOCK",
    "PRODUCT_INDEX",
    "PRODUCT_FUTURES",
    "PRODUCT_OPTIONS",
    "PRODUCT_MACRO",
    "PRODUCT_CRYPTO",
    "detect_product_type",
    "is_product",
    "provider_preference_for_symbol",
]
