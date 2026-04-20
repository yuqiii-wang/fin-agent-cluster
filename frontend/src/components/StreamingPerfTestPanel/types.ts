/** Per-thread performance session tracked in the grid. */
export interface ThreadSession {
  thread_id: string;
  /** Short display label, e.g. "Stream #1". */
  label: string;
  /**
   * Backend-driven status progression:
   *   connecting  — SSE connection not yet established (client-side)
   *   received    — backend confirmed it accepted the request
   *   preparing   — Celery worker started; graph building
   *   ingesting   — bulk ingest phase writing tokens to Redis stream
   *   sending     — pub phase streaming tokens to SSE
   *   running     — actively streaming (fallback / legacy)
   *   completed / failed / cancelled / stopped — terminal states
   */
  status: "connecting" | "received" | "preparing" | "ingesting" | "sending" | "running" | "completed" | "failed" | "cancelled" | "stopped";
  tokens: number;
  start_ms: number;
  /** Wall-clock ms when the last token was received. */
  last_token_ms: number;
  /** Raw text of the last token received (updated every second via tick). */
  last_token_text: string;
  /** True after the user clicked Stop or a done event arrived. */
  closed: boolean;
  /** Error message captured when the stream transitions to `failed` status. */
  error?: string;
  /** Ingest task phase — tracks how many tokens have been written to the perf stream. */
  ingest_produced?: number;
  /** Total tokens to ingest (matches PerfTestConfig.tokenCount). */
  ingest_total?: number;
  /** Approximate tokens-per-second during the ingest phase. */
  ingest_tps?: number;
  /** Current state of the ingest phase. */
  ingest_status?: "running" | "completed" | "timeout";
  /** Authoritative ingest duration in ms from the backend perf_ingest_complete event. */
  ingest_ms?: number;
  /** Current state of the pub phase. */
  pub_status?: "running" | "completed" | "failed";
  /** Wall-clock ms when the pub (streaming) phase started — i.e. when ingest completed. */
  pub_start_ms?: number;
  /** Backend-reported digest throughput (tokens/sec) from locust_complete event. */
  digest_tps?: number;
  /** Backend-reported digest duration in ms from locust_complete event (locust mode only). */
  digest_ms?: number;
  /** Publish mode this session was submitted with — "browser" or "locust". */
  pub_mode: "browser" | "locust";
}

/** User-configurable parameters for a perf-test run. */
export interface PerfTestConfig {
  /** Tokens to generate per stream (default 100,000). */
  tokenCount: number;
  /** Hard deadline in seconds passed directly to MockChatModel (default 60). */
  timeoutSecs: number;
  /** Publish mode: "browser" streams tokens to UI; "locust" digests silently and emits aggregated metrics. */
  pubMode: "browser" | "locust";
  /** Number of concurrent streams to spawn on initial load and Restart (default 5). */
  initialRequestCount: number;
}

export const DEFAULT_PERF_CONFIG: PerfTestConfig = {
  tokenCount: 100_000,
  timeoutSecs: 60,
  pubMode: "browser",
  initialRequestCount: 5,
};

/** Target token count per stream — kept in sync with DEFAULT_PERF_CONFIG for column math. */
export const TOTAL_TOKENS_PER_STREAM = DEFAULT_PERF_CONFIG.tokenCount;
