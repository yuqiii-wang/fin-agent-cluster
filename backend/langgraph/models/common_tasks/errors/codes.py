"""Error codes for the common_tasks module."""

from __future__ import annotations

STATS_TASK_NO_DATA = "STATS_TASK_NO_DATA"
STATS_TASK_PROVIDER_ERROR = "STATS_TASK_PROVIDER_ERROR"
STATS_TASK_CALC_ERROR = "STATS_TASK_CALC_ERROR"
STATS_TASK_CORR_INSUFFICIENT_DATA = "STATS_TASK_CORR_INSUFFICIENT_DATA"
STATS_TASK_UNSUPPORTED_PERIOD = "STATS_TASK_UNSUPPORTED_PERIOD"
STATS_TASK_PERIOD_FALLBACK = "STATS_TASK_PERIOD_FALLBACK"
STATS_TASK_PROVIDER_FALLBACK = "STATS_TASK_PROVIDER_FALLBACK"

NEWS_TASK_FETCH_ERROR = "NEWS_TASK_FETCH_ERROR"
NEWS_TASK_DIGEST_ERROR = "NEWS_TASK_DIGEST_ERROR"
NEWS_TASK_EMBED_ERROR = "NEWS_TASK_EMBED_ERROR"
NEWS_TASK_SUMMARY_WARN = "NEWS_TASK_SUMMARY_WARN"
NEWS_TASK_EMB_WARN = "NEWS_TASK_EMB_WARN"
NEWS_TASK_ALL_PROVIDERS_EMPTY = "NEWS_TASK_ALL_PROVIDERS_EMPTY"

STATS_TASK_JSON_INPUT_INVALID = "STATS_TASK_JSON_INPUT_INVALID"
STATS_TASK_JSON_INPUT_UNSUPPORTED_TYPE = "STATS_TASK_JSON_INPUT_UNSUPPORTED_TYPE"
STATS_TASK_SRC_REF_MISSING = "STATS_TASK_SRC_REF_MISSING"
STATS_TASK_SRC_REF_MISMATCH = "STATS_TASK_SRC_REF_MISMATCH"

STATS_TASK_ERRORS: dict[str, str] = {
    STATS_TASK_NO_DATA: "No stats data returned from provider for the given symbol/period.",
    STATS_TASK_PROVIDER_ERROR: "External stats provider raised an error.",
    STATS_TASK_CALC_ERROR: "Failed to compute technical indicators from OHLCV series.",
    STATS_TASK_CORR_INSUFFICIENT_DATA: "Insufficient bar data to compute Pearson correlation.",
    STATS_TASK_UNSUPPORTED_PERIOD: "Requested period is not supported for indicator calculation.",
    STATS_TASK_PERIOD_FALLBACK: "Requested period unavailable; fell back to a shorter period.",
    STATS_TASK_PROVIDER_FALLBACK: "Primary provider returned no data; fell back to an alternative provider.",
    STATS_TASK_JSON_INPUT_INVALID: "json_input failed schema validation for the declared data_type.",
    STATS_TASK_JSON_INPUT_UNSUPPORTED_TYPE: "json_input data_type is not yet supported.",
    STATS_TASK_SRC_REF_MISSING: "src_task_id provided but no task_executions row found in DB for that task.",
    STATS_TASK_SRC_REF_MISMATCH: "Injected data values could not be traced back to the source task output.",
}

DERIV_TASK_OPTIONS_FETCH_ERROR = "DERIV_TASK_OPTIONS_FETCH_ERROR"
DERIV_TASK_FUTURES_FETCH_ERROR = "DERIV_TASK_FUTURES_FETCH_ERROR"
DERIV_TASK_NO_OPTIONS = "DERIV_TASK_NO_OPTIONS"
DERIV_TASK_CONTRACT_PARSE_WARN = "DERIV_TASK_CONTRACT_PARSE_WARN"
DERIV_TASK_CALC_ERROR = "DERIV_TASK_CALC_ERROR"
DERIV_TASK_NO_CROSS = "DERIV_TASK_NO_CROSS"

DERIV_TASK_ERRORS: dict[str, str] = {
    DERIV_TASK_OPTIONS_FETCH_ERROR: "Failed to fetch options chain for one or more expiry dates.",
    DERIV_TASK_FUTURES_FETCH_ERROR: "Failed to fetch futures contract OHLCV; result skipped.",
    DERIV_TASK_NO_OPTIONS: "No options data returned for the symbol after processing all expiry dates.",
    DERIV_TASK_CONTRACT_PARSE_WARN: "OSI contract_name could not be parsed; contract row skipped.",
    DERIV_TASK_CALC_ERROR: "Failed to persist options stats to quant_options_stats / quant_derivative_stats.",
    DERIV_TASK_NO_CROSS: "No strike is shared by both calls and puts for an expiry; aggregate row skipped.",
}

NEWS_TASK_ERRORS: dict[str, str] = {
    NEWS_TASK_FETCH_ERROR: "Failed to fetch news or info from provider; partial results may be available.",
    NEWS_TASK_DIGEST_ERROR: "LLM digest call failed for one or more articles.",
    NEWS_TASK_EMBED_ERROR: "Embedding generation failed for one or more article summaries.",
    NEWS_TASK_SUMMARY_WARN: "do_summary task failed (soft); digest_news continues without LLM summaries.",
    NEWS_TASK_EMB_WARN: "do_emb task failed (soft); digest_news continues without vector embeddings.",
    NEWS_TASK_ALL_PROVIDERS_EMPTY: "All news providers (FMP and DDGS) returned empty results after retry — task failed.",
}

PDF_TASK_CONVERT_ERROR = "PDF_TASK_CONVERT_ERROR"
PDF_TASK_SOURCE_NOT_FOUND = "PDF_TASK_SOURCE_NOT_FOUND"
PDF_TASK_INVALID_SOURCE = "PDF_TASK_INVALID_SOURCE"

PDF_TASK_ERRORS: dict[str, str] = {
    PDF_TASK_CONVERT_ERROR: "markitdown conversion failed; check the PDF is a valid, non-encrypted document.",
    PDF_TASK_SOURCE_NOT_FOUND: "PDF file not found at the specified path.",
    PDF_TASK_INVALID_SOURCE: "source must be an absolute file path or an http/https URL.",
}

WEB_TASK_FETCH_ERROR = "WEB_TASK_FETCH_ERROR"
WEB_TASK_INVALID_URL = "WEB_TASK_INVALID_URL"
WEB_TASK_CONVERT_ERROR = "WEB_TASK_CONVERT_ERROR"
WEB_TASK_STUDY_ERROR = "WEB_TASK_STUDY_ERROR"

WEB_TASK_ERRORS: dict[str, str] = {
    WEB_TASK_FETCH_ERROR: "httpx HTTP request failed; check URL reachability and network connectivity.",
    WEB_TASK_INVALID_URL: "URL must use http or https scheme.",
    WEB_TASK_CONVERT_ERROR: "markitdown HTML conversion failed; the page may contain malformed markup.",
    WEB_TASK_STUDY_ERROR: "LLM content assessment failed or returned an unexpected structure.",
}

WEB_KNOWLEDGE_URL_NO_SYMBOL = "WEB_KNOWLEDGE_URL_NO_SYMBOL"
WEB_KNOWLEDGE_URL_DDGS_ERROR = "WEB_KNOWLEDGE_URL_DDGS_ERROR"

WEB_KNOWLEDGE_URL_ERRORS: dict[str, str] = {
    WEB_KNOWLEDGE_URL_NO_SYMBOL: "No symbol provided; cannot propose a web knowledge URL.",
    WEB_KNOWLEDGE_URL_DDGS_ERROR: "DDGS web search failed to return any URLs for the symbol.",
}

FUNDAMENTALS_TASK_FETCH_ERROR = "FUNDAMENTALS_TASK_FETCH_ERROR"
FUNDAMENTALS_TASK_PROVIDER_ERROR = "FUNDAMENTALS_TASK_PROVIDER_ERROR"
FUNDAMENTALS_TASK_CALC_ERROR = "FUNDAMENTALS_TASK_CALC_ERROR"
FUNDAMENTALS_TASK_NO_DATA = "FUNDAMENTALS_TASK_NO_DATA"

FUNDAMENTALS_TASK_ERRORS: dict[str, str] = {
    FUNDAMENTALS_TASK_FETCH_ERROR: "Failed to fetch fundamental data from provider for the given symbol/endpoint.",
    FUNDAMENTALS_TASK_PROVIDER_ERROR: "External fundamentals provider raised an unexpected error.",
    FUNDAMENTALS_TASK_CALC_ERROR: "Failed to aggregate or persist fundamental stats to quant_static_stats.",
    FUNDAMENTALS_TASK_NO_DATA: "All providers returned empty fundamental data for the symbol.",
}

LLM_ORCH_DECIDE_ERROR = "LLM_ORCH_DECIDE_ERROR"

LLM_ORCH_ERRORS: dict[str, str] = {
    LLM_ORCH_DECIDE_ERROR: "LLM orchestration failed to produce a valid decision or returned an unexpected structure.",
}

__all__ = [
    "STATS_TASK_NO_DATA",
    "STATS_TASK_PROVIDER_ERROR",
    "STATS_TASK_CALC_ERROR",
    "STATS_TASK_CORR_INSUFFICIENT_DATA",
    "STATS_TASK_UNSUPPORTED_PERIOD",
    "STATS_TASK_PERIOD_FALLBACK",
    "STATS_TASK_PROVIDER_FALLBACK",
    "STATS_TASK_ERRORS",
    "NEWS_TASK_FETCH_ERROR",
    "NEWS_TASK_DIGEST_ERROR",
    "NEWS_TASK_EMBED_ERROR",
    "NEWS_TASK_SUMMARY_WARN",
    "NEWS_TASK_EMB_WARN",
    "NEWS_TASK_ALL_PROVIDERS_EMPTY",
    "NEWS_TASK_ERRORS",
    "DERIV_TASK_OPTIONS_FETCH_ERROR",
    "DERIV_TASK_FUTURES_FETCH_ERROR",
    "DERIV_TASK_NO_OPTIONS",
    "DERIV_TASK_CONTRACT_PARSE_WARN",
    "DERIV_TASK_CALC_ERROR",
    "DERIV_TASK_NO_CROSS",
    "DERIV_TASK_ERRORS",
    "PDF_TASK_CONVERT_ERROR",
    "PDF_TASK_SOURCE_NOT_FOUND",
    "PDF_TASK_INVALID_SOURCE",
    "PDF_TASK_ERRORS",
    "WEB_TASK_FETCH_ERROR",
    "WEB_TASK_INVALID_URL",
    "WEB_TASK_CONVERT_ERROR",
    "WEB_TASK_STUDY_ERROR",
    "WEB_TASK_ERRORS",
    "WEB_KNOWLEDGE_URL_NO_SYMBOL",
    "WEB_KNOWLEDGE_URL_DDGS_ERROR",
    "WEB_KNOWLEDGE_URL_ERRORS",
    "LLM_ORCH_DECIDE_ERROR",
    "LLM_ORCH_ERRORS",
]
