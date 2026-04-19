/** Per-thread performance session tracked in the grid. */
export interface ThreadSession {
  thread_id: string;
  /** Short display label, e.g. "Stream #1". */
  label: string;
  status: "connecting" | "running" | "completed" | "failed" | "cancelled" | "stopped";
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
  /** Current state of the pub phase. */
  pub_status?: "running" | "completed" | "failed";
  /** Wall-clock ms when the pub (streaming) phase started — i.e. when ingest completed. */
  pub_start_ms?: number;
}

/** User-configurable parameters for a perf-test run. */
export interface PerfTestConfig {
  /** Tokens to generate per stream (default 100,000). */
  tokenCount: number;
  /** Hard deadline in seconds passed directly to MockChatModel (default 60). */
  timeoutSecs: number;
}

export const DEFAULT_PERF_CONFIG: PerfTestConfig = {
  tokenCount: 100_000,
  timeoutSecs: 60,
};

/** Target token count per stream — kept in sync with DEFAULT_PERF_CONFIG for column math. */
export const TOTAL_TOKENS_PER_STREAM = DEFAULT_PERF_CONFIG.tokenCount;
