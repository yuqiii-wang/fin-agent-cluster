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
   *   digesting   — pub phase streaming tokens to SSE
   *   running     — actively streaming (fallback / legacy)
   *   completed / failed / cancelled / timeout — terminal states
   */
  status: "connecting" | "received" | "preparing" | "ingesting" | "digesting" | "running" | "completed" | "failed" | "cancelled" | "timeout";
  tokens: number;
  start_ms: number;
  /** Wall-clock ms when the last token was received. */
  last_token_ms: number;
  /** Raw text of the last token received (updated every second via tick). */
  last_token_text: string;
  /** True after the user clicked Cancel or a done event arrived. */
  closed: boolean;
  /** Test mode this session was spawned under — frozen at creation time. */
  test_mode: "throughput" | "concurrency";
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
  /** Current adaptive read batch size during concurrent Phase-2 (from perf_concurrent_status). */
  concurrent_batch_size?: number;
  /** Live digest TPS during concurrent Phase-2 (from perf_concurrent_status). */
  concurrent_digest_tps?: number;
  /** Live ingest TPS during concurrent Phase-2 (from perf_concurrent_status). */
  concurrent_ingest_tps?: number;
  /** Redis stream backlog during concurrent Phase-2 (from perf_concurrent_status). */
  concurrent_stream_len?: number;
  /** Token count of the very first perf_token_batch event received. */
  batch_first?: number;
  /** Maximum token count seen across all perf_token_batch events. */
  batch_max?: number;
  /** Running average token count across all perf_token_batch events. */
  batch_ave?: number;
  /** Token count of the most recent perf_token_batch event. */
  batch_last?: number;
  /**
   * Wall-clock ms when the first `perf_token_batch` event was received.
   * Used as the authoritative digest start for accurate throughput computation —
   * excludes ingest latency from the streaming TPS measurement.
   */
  digest_start_ms?: number;
  /**
   * Per-second token-count history accumulated while streaming.
   * Each element is the number of tokens received in that 1-second bucket,
   * starting from the first second after `digest_start_ms`.
   * Used to render the per-row TPS sparkline bar chart.
   */
  tps_history?: number[];
  /**
   * Accumulated streaming text for the Streaming Output panel.
   * Built by expanding each `perf_token_batch` count into `count` individual
   * `"· "` markers — one per token — so the display flows token-by-token.
   * Capped at 6 000 characters (oldest chars trimmed from the front).
   */
  stream_text?: string;
}

/** Terminal session statuses — lifecycle has ended and all metrics should be frozen. */
export const TERMINAL_STATUSES: ReadonlySet<ThreadSession["status"]> = new Set([
  "completed", "failed", "cancelled", "timeout",
]);

/** User-configurable parameters for a perf-test run. */
export interface PerfTestConfig {
  /** Test mode: "throughput" measures max tokens/s; "concurrency" measures steady-rate SSE throughput. */
  testMode: "throughput" | "concurrency";
  /** Tokens to generate per stream — used in throughput mode (default 100,000). */
  tokenCount: number;
  /** Target ingest rate per stream in tokens/sec — used in concurrency mode (default 500). */
  tokenPerSec: number;
  /** Hard deadline in seconds passed directly to MockChatModel (default 20). */
  timeoutSecs: number;
  /** Number of concurrent streams to spawn on initial load and Restart (default 5). */
  initialRequestCount: number;
}

/**
 * Pending token-batch data accumulated per-session in a ref between 100ms flush
 * ticks.  Written by `onPerfTokenBatch` in `usePerfSession`; consumed and cleared
 * by the 100ms tick in `useSessionManager`.
 *
 * Buffering all SSE token events into this ref and flushing at most once per
 * 100ms tick dramatically reduces the number of React state updates (and
 * therefore re-renders) when hundreds of streams are running concurrently.
 */
export interface PendingTokenPatch {
  /** Accumulated token count since the last tick flush. */
  tokensDelta: number;
  /** Timestamp of the most recent token batch. */
  last_token_ms: number;
  /** Timestamp of the FIRST ever token batch — sets digest_start_ms on flush. */
  first_token_ms: number;
  /** Count of the first batch (written to s.batch_first if not yet set). */
  batch_first: number;
  /** Max single-batch count seen so far. */
  batch_max: number;
  /** Running average batch count. */
  batch_ave: number;
  /** Count of the most recent batch. */
  batch_last: number;
  /** Latest stream text snippet. */
  stream_text: string;
  /** Non-null when the session status needs to be promoted to "digesting". */
  status_transition?: "digesting";
  /**
   * When set, override s.tokens with this authoritative value instead of
   * s.tokens + tokensDelta.  Used for the final batch so the displayed count
   * freezes at the exact closure-tracked total rather than a React-lagged value.
   */
  forceTokensTotal?: number;
}

export const DEFAULT_PERF_CONFIG: PerfTestConfig = {
  testMode: "throughput",
  tokenCount: 100_000,
  tokenPerSec: 500,
  timeoutSecs: 20,
  initialRequestCount: 5,
};

/** Target token count per stream — kept in sync with DEFAULT_PERF_CONFIG for column math. */
export const TOTAL_TOKENS_PER_STREAM = DEFAULT_PERF_CONFIG.tokenCount;
