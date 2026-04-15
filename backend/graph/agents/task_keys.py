"""Static task key registry for all agent nodes.

Task keys follow the dot-separated pattern::

    <node>.<method_or_task>[.<ticker_or_symbol>].<quant|news>

Every key ends with either ``.quant`` or ``.news`` to indicate the data type:

* ``.quant`` — numerical / chart data (OHLCV bars, yield curves, macro rates).
  Displayed as candlestick / line charts in the UI.
* ``.news``  — text / article data (LLM outputs, news enrichment, pipeline steps).
  Displayed as text panels in the UI.

The type suffix allows callers to derive display intent from the key alone without
maintaining a separate allowlist.  Use :func:`is_quant_key` / :func:`is_text_key`
for programmatic checks.

``LLM_STREAM_KEYS`` enumerates every key whose task calls ``stream_text_task``
or ``stream_llm_task`` — used by the Tasks API to classify streaming vs
non-streaming tasks without AST scanning.

``STATIC_KEYS`` enumerates every fully-deterministic (non-dynamic) task key.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Type suffix constants
# ---------------------------------------------------------------------------

QUANT_SUFFIX: str = ".quant"
"""Suffix for tasks that produce numerical / chart output."""

NEWS_SUFFIX: str = ".text"
"""Suffix for tasks that produce text / article output."""


def is_quant_key(task_key: str) -> bool:
    """Return ``True`` if *task_key* ends with ``.quant``.

    Args:
        task_key: Full dot-separated task key.

    Returns:
        ``True`` when this task produces quant / chart data.
    """
    return task_key.endswith(QUANT_SUFFIX)


def is_text_key(task_key: str) -> bool:
    """Return ``True`` if *task_key* ends with ``.text``.

    Args:
        task_key: Full dot-separated task key.

    Returns:
        ``True`` when this task produces text / article data.
    """
    return task_key.endswith(NEWS_SUFFIX)


# ---------------------------------------------------------------------------
# query_optimizer keys  (.text — all produce or process text / JSON)
# ---------------------------------------------------------------------------

QO_COMPREHEND_BASICS: str = "query_optimizer.comprehend_basics.text"
"""Stream LLM JSON output for initial query understanding."""

QO_VALIDATE_BASICS: str = "query_optimizer.validate_basics.text"
"""Correct region / index / industry against SQL static data."""

QO_POPULATE_JSON: str = "query_optimizer.populate_json.text"
"""Build full QueryOptimizerOutput from validated basics."""

QO_POPULATE_SEC_PROFILE: str = "query_optimizer.populate_sec_profile.text"
"""Ensure a sec_profiles row exists for the resolved ticker (upsert from yfinance overview)."""

# ---------------------------------------------------------------------------
# decision_maker keys  (.text — LLM inference and report persistence)
# ---------------------------------------------------------------------------

DM_LLM_INFER: str = "decision_maker.llm_infer.text"
"""Stream LLM decision report inference."""

DM_DB_INSERT_REPORT: str = "decision_maker.db_insert_report.text"
"""Persist DecisionReport to fin_strategies.reports."""

# ---------------------------------------------------------------------------
# market_data_collector static keys
# ---------------------------------------------------------------------------

MD_BOND: str = "market_data_collector.bond.quant"
"""Fetch US Bond yield curve tenors."""

# ---------------------------------------------------------------------------
# market_data_collector dynamic key factories
# ---------------------------------------------------------------------------


def md_ohlcv(granularity: str) -> str:
    """Return the task key for a primary OHLCV window fetch.

    Args:
        granularity: Window granularity string, e.g. ``'15min'``, ``'1h'``,
                     ``'1day'``, ``'1mo'``.

    Returns:
        Full task key, e.g. ``'market_data_collector.ohlcv.15min.quant'``.
    """
    return f"market_data_collector.ohlcv.{granularity}.quant"


def md_peer_ohlcv(peer: str) -> str:
    """Return the task key for a peer-ticker OHLCV fetch.

    Args:
        peer: Peer ticker symbol, e.g. ``'MSFT'``.

    Returns:
        Full task key, e.g. ``'market_data_collector.peer_ohlcv.MSFT.quant'``.
    """
    return f"market_data_collector.peer_ohlcv.{peer}.quant"


def md_index_ohlcv(idx: str) -> str:
    """Return the task key for a benchmark-index OHLCV fetch.

    Args:
        idx: Index ticker symbol, e.g. ``'^GSPC'``.

    Returns:
        Full task key, e.g. ``'market_data_collector.index_ohlcv.^GSPC.quant'``.
    """
    return f"market_data_collector.index_ohlcv.{idx}.quant"


def md_macro(macro_key: str) -> str:
    """Return the task key for a macro commodity / rate fetch.

    Args:
        macro_key: Macro identifier key, e.g. ``'gold'``, ``'crude_oil'``.

    Returns:
        Full task key, e.g. ``'market_data_collector.macro.gold.quant'``.
    """
    return f"market_data_collector.macro.{macro_key}.quant"


def md_web_search(label: str) -> str:
    """Return the task key for a named news web-search query.

    Args:
        label: News query label, e.g. ``'company'``, ``'macro'``, ``'financial_report'``.

    Returns:
        Full task key, e.g. ``'market_data_collector.web_search.company.news'``.
    """
    return f"market_data_collector.web_search.{label}.text"


# ---------------------------------------------------------------------------
# Classification sets
# ---------------------------------------------------------------------------

LLM_STREAM_KEYS: frozenset[str] = frozenset(
    {
        QO_COMPREHEND_BASICS,
        DM_LLM_INFER,
    }
)
"""Keys whose tasks emit token-stream SSE events via ``stream_text_task`` / ``stream_llm_task``."""

STATIC_KEYS: frozenset[str] = frozenset(
    {
        QO_COMPREHEND_BASICS,
        QO_VALIDATE_BASICS,
        QO_POPULATE_JSON,
        DM_LLM_INFER,
        DM_DB_INSERT_REPORT,
        MD_BOND,
    }
)
"""All fully-static (non-dynamic) task keys defined at import time."""
