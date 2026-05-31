from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    # ── Database / API keys ─────────────────────────────────────
    DATABASE_PG_URL: str = "postgresql://admin:P%40ssw0rd123@127.0.0.1:6543/fin_trading"
    # Read replica URL.  When set, SELECT queries are routed here; writes
    # always go to DATABASE_PG_URL (the primary).  Leave empty to use the
    # primary for both reads and writes (single-instance fallback).
    DATABASE_PG_READ_URL: str = "postgresql://admin:P%40ssw0rd123@127.0.0.1:6544/fin_trading"
    DATABASE_REDIS_URL: str = "redis://127.0.0.1:3456"
    # Ordered list of Redis node URLs for hash-based shard routing.
    # Comma-separated when provided via environment variable, e.g.:
    #   DATABASE_REDIS_NODES=redis://redis-0:6379,redis://redis-1:6379
    # When empty, the router falls back to DATABASE_REDIS_URL as a single node.
    DATABASE_REDIS_NODES: list[str] = ["redis://127.0.0.1:3456", "redis://127.0.0.1:3457"]
    DB_CONNECT_TIMEOUT_SECONDS: int = 8
    # ── LLM provider selection ─────────────────────────────────────────────
    # Which LLM backend to use: ark | gemini | ollama | mock
    LLM_PROVIDER: str = "ollama"

    # ── Volcano Engine ARK / Doubao ──────────────────────────────────────────
    ARK_API_KEY: Optional[str] = None
    ARK_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3"
    ARK_MODEL: str = "doubao-seed-2-0-mini-260215"

    # ── Google Gemini ─────────────────────────────────────────────────────────
    GOOGLE_GEMINI_API_KEY: Optional[str] = None
    GOOGLE_GEMINI_MODEL: str = "gemini-2.5-flash"

    # ── Embedding ─────────────────────────────────────────────────────────────
    # Provider: google | ollama | mock
    EMBEDDING_PROVIDER: str = "ollama"
    GOOGLE_EMBEDDING_MODEL: str = "models/text-embedding-004"
    GOOGLE_EMBEDDING_DIMENSIONS: int = 768

    # Stats data provider: mock | yfinance | fmp
    # mock    — in-process mock data, no external calls (default)
    # yfinance — free Yahoo Finance via the yfinance library
    # fmp      — Financial Modeling Prep REST API (requires FMP_API_KEY)
    STATS_PROVIDER: str = "mock"
    ALPHAVANTAGE_API_KEY: Optional[str] = None
    FMP_API_KEY: Optional[str] = None
    FMP_BASE_URL: str = "https://financialmodelingprep.com/stable"
    FASTAPI_PORT: int = 8432
    # Number of main thread FastAPI instances (must match run.py --runner-instances and nginx-api.conf targets).
    RUNNER_INSTANCE_COUNT: int = 4
    FASTAPI_ASSISTANT_PORT: int = 8436
    ASSISTANT_INSTANCE_COUNT: int = 2
    # Number of Celery workers bound to each runner instance (completion tasks only).
    CELERY_WORKERS_PER_INSTANCE: int = 2
    # Number of concurrent task slots per completion Celery worker process (prefork child count).
    # Completion tasks are fast (<500ms), so 4 is sufficient per worker.
    CELERY_WORKER_CONCURRENCY: int = 4
    # Number of dedicated stream Celery workers per runner instance.
    # Stream tasks hold a slot for the full LLM stream duration (e.g. 10s).
    # Kept separate from completion workers so fast completion tasks are never
    # blocked by long-running stream tasks.
    CELERY_STREAM_WORKERS_PER_INSTANCE: int = 2
    # Concurrent slots per stream worker.  Increase to raise peak streaming concurrency.
    # Total stream slots = RUNNER_INSTANCE_COUNT * CELERY_STREAM_WORKERS_PER_INSTANCE * CELERY_STREAM_WORKER_CONCURRENCY.
    CELERY_STREAM_WORKER_CONCURRENCY: int = 4
    # Port this specific main thread instance is bound to.

    # ── Thread ownership lock (Redis) ─────────────────────────────────────────
    # TTL (seconds) for the per-thread Redis ownership lock.
    # Must exceed the longest expected graph run so the lock is not lost mid-run.
    THREAD_LOCK_TTL_SECONDS: int = 60
    # How often (seconds) the lock-renewal background task extends the TTL.
    # Must be strictly less than THREAD_LOCK_TTL_SECONDS to avoid expiry gaps.
    THREAD_LOCK_RENEW_INTERVAL_SECONDS: int = 25
    # Timeout (seconds) for the TCP liveness check against another main thread.
    MAIN_THREAD_HEALTH_CHECK_TIMEOUT_SECONDS: float = 2.0
    # Outbound HTTP proxy for all external calls (LLM, market-data, news, embeddings).
    # Example: HTTP_PROXY=http://127.0.0.1:7890
    # Leave unset to connect directly.
    HTTP_PROXY: Optional[str] = None

    # ── Playwright ────────────────────────────────────────────────────────────
    # Absolute path to the Chromium executable used by Playwright.
    # Leave unset to let Playwright auto-locate the browser it installed via
    # `playwright install chromium`.
    # Example (WSL2): PLAYWRIGHT_CHROMIUM_PATH=/root/.cache/ms-playwright/chromium-1169/chrome-linux/chrome
    PLAYWRIGHT_CHROMIUM_PATH: Optional[str] = None
    # Set True (default) when running in WSL2 / Docker / as root where Chrome
    # requires --no-sandbox and --disable-dev-shm-usage to start.
    PLAYWRIGHT_NO_SANDBOX: bool = True

    # ── Ollama LLM ────────────────────────────────────────────────────────────
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_LLM_MODEL: str = "qwen3.5-27b-instruct"
    OLLAMA_EMBED_MODEL: str = "qwen3-0.6b-emb"
    # Number of model layers to offload to GPU (-1 = auto, 0 = CPU only).
    # Set explicitly to keep the full model resident in VRAM.
    OLLAMA_NUM_GPU: int = 65

    # ── API Gateway ──────────────────────────────────────────────
    # Internal HTTP URL of nginx-api (plain HTTP, no TLS required for
    # container-internal calls from the backend or health-check scripts).
    API_GATEWAY_URL: str = "http://127.0.0.1:8888"

    # ── Web search ───────────────────────────────────────────────────────────
    # Provider: auto | bing | google_cse | volcengine
    WEB_SEARCH_PROVIDER: str = "auto"
    BING_SEARCH_API_KEY: Optional[str] = None
    BING_SEARCH_ENDPOINT: str = "https://api.bing.microsoft.com/v7.0/news/search"
    GOOGLE_CSE_API_KEY: Optional[str] = None
    GOOGLE_CSE_CX: Optional[str] = None
    VOLCENGINE_ACCESS_KEY_ID: Optional[str] = None
    VOLCENGINE_SECRET_ACCESS_KEY: Optional[str] = None
    VOLC_SEARCH_HOST: str = "open.volcengineapi.com"
    VOLC_SEARCH_REGION: str = "cn-north-1"
    VOLC_SEARCH_SERVICE: str = "search_platform"

    # ── Redis Streams (MQ / buffer layer) ────────────────────────────────────
    # Soft cap on each stream's entry count (XADD MAXLEN ~).
    # Sized for high-concurrency: 100 sessions × ~10 XADD/sec = 1,000/sec per
    # shard; 1,000,000 entries gives ~100 s of buffer before eviction under load.
    STREAM_MAX_LEN: int = 1000000

    # ── Graph Runner (dedicated asyncio process) ──────────────────────────────
    # Redis Stream key where FastAPI enqueues new graph runs.
    GRAPH_QUEUE_STREAM: str = "fin:graphs:queue"
    # Redis key prefix for per-thread cancel flags (SET key 1 EX ttl).
    GRAPH_CANCEL_KEY_PREFIX: str = "fin:cancel:"
    # TTL (seconds) for cancel flags — must exceed the longest graph run.
    GRAPH_CANCEL_TTL_SECONDS: int = 600
    # Consumer group name for the graph runner stream.
    GRAPH_QUEUE_GROUP: str = "graph-runners"
    # How long (ms) the runner blocks on XREADGROUP before re-checking shutdown.
    GRAPH_QUEUE_BLOCK_MS: int = 1000

    # ── Centrifugo real-time messaging ────────────────────────────────────────
    # Internal HTTP API URLs of the two Centrifugo nodes (WSL2 → Docker via mapped ports).
    # Comma-separated when provided via environment variable.
    # Ordering MUST match DATABASE_REDIS_NODES: index 0 = centrifugo-llm-0 → redis-0.
    # These nodes are ONLY used for LLM token streaming (Redis Stream consumers).
    CENTRIFUGO_NODES: list[str] = [
        "http://127.0.0.1:8101",
        "http://127.0.0.1:8102",
    ]
    # Internal HTTP API URLs of the dedicated SSE Centrifugo nodes (centrifugo-sse-0/1).
    # All lifecycle events (started, completed, done, query_*, node_*, stream_*) are
    # published here via FastAPI HTTP API.  Thread sharded by SHA-256 % len.
    # Token events stay in centrifugo-llm-0/1.
    CENTRIFUGO_SSE_NODES: list[str] = [
        "http://127.0.0.1:8103",
        "http://127.0.0.1:8104",
    ]
    # Shared HMAC secret used to sign Centrifugo connection / subscription JWTs.
    CENTRIFUGO_SECRET: str = "centrifugo-dev-secret-key"
    # API key for Centrifugo server-side HTTP API calls (publish, etc.).
    CENTRIFUGO_API_KEY: str = "centrifugo-api-key"
    # Shared secret used to authenticate inbound Centrifugo RPC proxy calls.
    # Must match the ``static_http_headers.X-Centrifugo-Proxy-Key`` value in
    # centrifugo-sse-0/1 config.json.
    CENTRIFUGO_RPC_PROXY_KEY: str = "centrifugo-rpc-proxy-key"
    # Public WebSocket base URL used by the frontend to connect.
    # Points to the nginx-ui TLS port (22332) which speaks HTTP/1.1 (no http2
    # directive), so the browser negotiates HTTP/1.1 and the standard WebSocket
    # Upgrade mechanism works.  nginx proxies each /centrifugo-{tier}-{shard}/
    # location directly to the corresponding Centrifugo container over plain
    # HTTP/1.1 WebSocket.
    CENTRIFUGO_PUBLIC_BASE: str = "wss://localhost:22332"

    # ── Assistant status verifier ─────────────────────────────────────────────
    STATUS_VERIFIER_INTERVAL_SECS: int = 30
    STATUS_VERIFIER_LOOKBACK_SECS: int = 3600

    # ── Assistant done verifier ───────────────────────────────────────────────
    DONE_VERIFIER_INTERVAL_SECS: int = 2
    DONE_VERIFIER_MAX_RETRIES: int = 30

    # ── Sandbox (agent code execution) ────────────────────────────────────────
    # Root directory for sandbox temp dirs; created at runtime if missing.
    # Each execution gets a fresh sub-directory deleted on completion.
    SANDBOX_DIR: str = "/tmp/fin_sandbox"
    # Wall-clock timeout (seconds) for each sandboxed execution.
    SANDBOX_TIMEOUT_SECONDS: int = 60
    # Max virtual memory per sandbox process (megabytes, RLIMIT_AS).
    SANDBOX_MAX_MEMORY_MB: int = 256
    # Max CPU time per sandbox process (seconds, RLIMIT_CPU).
    SANDBOX_MAX_CPU_SECONDS: int = 30
    # Max spawnable child processes from the sandbox process (RLIMIT_NPROC).
    SANDBOX_MAX_PROCS: int = 64
    # Max open file descriptors for the sandbox process (RLIMIT_NOFILE).
    SANDBOX_MAX_OPEN_FILES: int = 64
    # Max combined stdout+stderr characters returned; excess is truncated.
    SANDBOX_MAX_OUTPUT_BYTES: int = 1_048_576  # 1 MB
    # Ordered list of sandbox runner HTTP base URLs; sharded by thread_id.
    # Requests are proxied through nginx-internal so the Windows host backend can
    # reach runners that stay isolated on the internal sandbox Docker network.
    SANDBOX_RUNNER_NODES: list[str] = [
        "http://127.0.0.1:8888/_sandbox/0",
        "http://127.0.0.1:8888/_sandbox/1",
    ]
    # HTTP read timeout for /execute calls; should exceed SANDBOX_TIMEOUT_SECONDS.
    SANDBOX_RUNNER_TIMEOUT_SECONDS: int = 90

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

    @_fv("CENTRIFUGO_SSE_NODES", mode="before")
    @classmethod
    def _coerce_centrifugo_sse_nodes(cls, v: object) -> object:
        """Coerce a comma-separated string into a list before validation."""
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                return []
            return [node.strip() for node in stripped.split(",") if node.strip()]
        return v

    @_fv("SANDBOX_RUNNER_NODES", mode="before")
    @classmethod
    def _coerce_sandbox_runner_nodes(cls, v: object) -> object:
        """Coerce a comma-separated string into a list before validation."""
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                return []
            return [node.strip() for node in stripped.split(",") if node.strip()]
        return v

    model_config = {"env_file": str(_ENV_FILE), "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
