from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    # ── LLM provider selection ──────────────────────────────────
    LLM_PROVIDER: str = "ark"  # ark | gemini | ollama

    # ── Volcano Engine ARK / Doubao ─────────────────────────────
    ARK_API_KEY: str = ""
    ARK_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3"
    ARK_MODEL: str = "doubao-seed-2-0-mini-260215"

    # ── Google Gemini ───────────────────────────────────────────
    GOOGLE_GEMINI_API_KEY: Optional[str] = None
    GOOGLE_GEMINI_MODEL: str = "gemini-2.5-flash"

    # ── Google Embedding ────────────────────────────────────────
    EMBEDDING_PROVIDER: str = "google"  # google | ollama
    GOOGLE_EMBEDDING_MODEL: str = "models/text-embedding-004"
    GOOGLE_EMBEDDING_DIMENSIONS: int = 768  # native text-embedding-004 output dim

    # ── Local Ollama ────────────────────────────────────────────
    OLLAMA_SERVER_URL: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "qwen3.5-27b"
    OLLAMA_EMBED_MODEL: str = "qwen3-0.6b-emb"

    # ── Database / API keys ─────────────────────────────────────
    DATABASE_PG_URL: str
    # Read replica URL.  When set, SELECT queries are routed here; writes
    # always go to DATABASE_PG_URL (the primary).  Leave empty to use the
    # primary for both reads and writes (single-instance fallback).
    DATABASE_PG_READ_URL: str = ""
    DATABASE_REDIS_URL: str = "redis://127.0.0.1:3456"
    # Ordered list of Redis node URLs for hash-based shard routing.
    # Comma-separated when provided via environment variable, e.g.:
    #   DATABASE_REDIS_NODES=redis://redis-0:6379,redis://redis-1:6379
    # When empty, the router falls back to DATABASE_REDIS_URL as a single node.
    DATABASE_REDIS_NODES: list[str] = []
    DB_CONNECT_TIMEOUT_SECONDS: int = 8
    ALPHAVANTAGE_API_KEY: Optional[str] = None
    FMP_API_KEY: Optional[str] = None
    FMP_BASE_URL: str = "https://financialmodelingprep.com/stable"
    # Stats data provider: mock | yfinance | fmp
    # mock    — in-process mock data, no external calls (default)
    # yfinance — free Yahoo Finance via the yfinance library
    # fmp      — Financial Modeling Prep REST API (requires FMP_API_KEY)
    STATS_PROVIDER: str = "mock"
    FASTAPI_PORT: int = 8432
    # Number of runner FastAPI instances (must match run.py --runner-instances and Kong targets).
    RUNNER_INSTANCE_COUNT: int = 4
    # Base port for assistant FastAPI instances (non-LangGraph).
    # Runner instances start at FASTAPI_PORT; assistants at FASTAPI_ASSISTANT_PORT.
    FASTAPI_ASSISTANT_PORT: int = 8436
    # Number of assistant FastAPI instances (must match run.py --assistant-instances and Kong targets).
    ASSISTANT_INSTANCE_COUNT: int = 2
    # Outbound HTTP proxy for all external calls (LLM, market-data, news, embeddings).
    # Example: HTTP_PROXY=http://127.0.0.1:7890
    # Leave unset to connect directly.
    HTTP_PROXY: Optional[str] = None

    # ── Kong AI Gateway ──────────────────────────────────────────
    # Set to Kong's proxy URL when LLM_PROVIDER=kong_ai.
    # Kong's ai-proxy plugin then manages model routing and API-key injection.
    # Example: KONG_AI_PROXY_URL=http://localhost:8000/llm
    KONG_AI_PROXY_URL: Optional[str] = None

    # Internal URL of the Kong API gateway used for perf-test SSE consumption.
    # Use the HTTP/1.1 port (8888) — no TLS required for internal connections.
    KONG_API_URL: str = "http://127.0.0.1:8888"

    # ── Web search provider selection ────────────────────────────
    # Choices: auto | ddgs | bing | google | volc
    # auto = try bing → google → ddgs in order (first configured one wins)
    WEB_SEARCH_PROVIDER: str = "auto"

    # Bing News Search API v7 (Azure Cognitive Services)
    BING_SEARCH_API_KEY: Optional[str] = None
    BING_SEARCH_ENDPOINT: str = "https://api.bing.microsoft.com/v7.0/news/search"

    # Google Custom Search API
    GOOGLE_CSE_API_KEY: Optional[str] = None
    GOOGLE_CSE_CX: Optional[str] = None  # Custom Search Engine ID

    # Volcano Engine web search
    VOLCENGINE_ACCESS_KEY_ID: Optional[str] = None
    VOLCENGINE_SECRET_ACCESS_KEY: Optional[str] = None
    VOLC_SEARCH_HOST: str = "open.volcengineapi.com"
    VOLC_SEARCH_REGION: str = "cn-north-1"
    VOLC_SEARCH_SERVICE: str = "search_platform"

    # ── Redis Streams (MQ / buffer layer) ────────────────────────────────────
    # Soft cap on each stream's entry count (XADD MAXLEN ~).
    # Sized for high-concurrency: 100 sessions × ~10 XADD/sec = 1,000/sec per
    # shard; 100,000 entries gives ~100 s of buffer before eviction under load.
    STREAM_MAX_LEN: int = 100000

    # ── Centrifugo real-time messaging ────────────────────────────────────────
    # Internal HTTP API URLs of the two Centrifugo nodes (WSL2 → Docker via mapped ports).
    # Comma-separated when provided via environment variable.
    # Ordering MUST match DATABASE_REDIS_NODES: index 0 = centrifugo-0 → redis-0.
    CENTRIFUGO_NODES: list[str] = [
        "http://127.0.0.1:8101",
        "http://127.0.0.1:8102",
    ]
    # Shared HMAC secret used to sign Centrifugo connection / subscription JWTs.
    CENTRIFUGO_SECRET: str = "centrifugo-dev-secret-key"
    # API key for Centrifugo server-side HTTP API calls (publish, etc.).
    CENTRIFUGO_API_KEY: str = "centrifugo-api-key"
    # Public WebSocket base URL used by the frontend to connect.
    # Dev: wss://localhost:8443 (Kong HTTPS/HTTP2 port). Prod: wss://your-domain.
    CENTRIFUGO_PUBLIC_BASE: str = "wss://localhost:8443"

    # ── Assistant status verifier ─────────────────────────────────────────────
    # How often (seconds) the assistant background verifier checks for unACKed
    # query-status phases and re-publishes them via Centrifugo.
    STATUS_VERIFIER_INTERVAL_SECS: int = 30
    # How far back (seconds) the verifier looks when querying for active queries.
    # Should be >= the longest expected query duration to avoid missing stale phases.
    STATUS_VERIFIER_LOOKBACK_SECS: int = 3600

    model_config = {"env_file": str(_ENV_FILE), "env_file_encoding": "utf-8", "extra": "ignore"}

    from pydantic import field_validator as _fv

    @_fv("DATABASE_REDIS_NODES", mode="before")
    @classmethod
    def _coerce_redis_nodes(cls, v: object) -> object:
        """Coerce a comma-separated string into a list before validation."""
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                return []
            return [node.strip() for node in stripped.split(",") if node.strip()]
        return v

    @_fv("CENTRIFUGO_NODES", mode="before")
    @classmethod
    def _coerce_centrifugo_nodes(cls, v: object) -> object:
        """Coerce a comma-separated string into a list before validation."""
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                return []
            return [node.strip() for node in stripped.split(",") if node.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
