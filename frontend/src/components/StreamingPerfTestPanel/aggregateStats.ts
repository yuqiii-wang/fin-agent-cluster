import type { ThreadSession } from "./types";
import { TERMINAL_STATUSES } from "./types";

/**
 * A session is "suspicious" (out-of-sync) when it is in the digesting phase but
 * has not received any tokens for more than STALE_TOKEN_THRESHOLD_MS milliseconds.
 * These sessions are excluded from aggregate token-audit metrics because their
 * accumulated digest time and tps_history are no longer representative.
 */
const STALE_TOKEN_THRESHOLD_MS = 10;

export function isSessionSuspicious(s: ThreadSession, nowMs: number): boolean {
  return (
    !s.closed &&
    !TERMINAL_STATUSES.has(s.status) &&
    s.digest_start_ms != null &&
    nowMs - s.last_token_ms > STALE_TOKEN_THRESHOLD_MS
  );
}

/** Aggregate performance statistics computed across all concurrent streams. */
export interface AggregateStats {
  /**
   * Max total tokens/s summed across all concurrent streams in any single
   * 1-second window.  Computed by time-aligning each session's `tps_history`
   * at its `digest_start_ms` and then taking `max(sum over streams, per bucket)`.
   */
  peakSumConcurrent: number | null;
  /**
   * Max tokens/s achieved by any single stream in any 1-second window.
   * `max(max(tps_history) for each stream)`.
   */
  peakSingleStream: number | null;
  /**
   * Mean total tokens/s across all occupied 1-second buckets.
   * Each bucket value is the sum of all streams active in that second;
   * the average is taken over all buckets that had at least one stream active.
   */
  aveConcurrent: number | null;
  /**
   * Maximum latency from stream start until the first `perf_token_batch` event.
   * `max(digest_start_ms - start_ms)` across all sessions that have received at
   * least one token batch.  Reflects how long the slowest stream waited before
   * the SSE token pipe opened.
   */
  maxFirstTokenLatencyMs: number | null;
  /** Number of browser-mode sessions (with tps_history) included in the computation. */
  sampleCount: number;
  /**
   * Maximum number of concurrency-mode sessions that were simultaneously stable
   * across all 1-second windows.  Tracked by useSessionManager and threaded in
   * here; null when no concurrency sessions have been run.
   */
  maxStableCount: number | null;
  /**
   * Maximum number of sessions simultaneously in the digesting phase across
   * all 1-second windows (all test modes).  Used as the "Max Num Stable Streams"
   * value for throughput-mode runs where stability is not applicable.
   */
  maxDigestingCount: number;
}

/**
 * Compute aggregate throughput statistics from an array of perf-test sessions.
 *
 * Only sessions that have at least one entry in `tps_history` are included.
 * Sessions identified as "suspicious" (no tokens for ≥3 s while still running)
 * are excluded from the bucket-sum computation so stalled streams do not skew
 * Peak Sum Read Batch or Ave Read Batch.
 *
 * Alignment: each session's history is pinned to its `digest_start_ms`
 * (falling back to `pub_start_ms` then `start_ms`) so concurrent streams are
 * correctly summed by wall-clock second rather than by relative offset.
 *
 * @param nowMs         Wall-clock time (Date.now()) used for suspicious detection.
 *                      Defaults to 0 so terminal-only datasets (activeCount=0)
 *                      are unaffected (no session can be suspicious when closed).
 * @param maxStableCount  Caller-tracked peak stable concurrency count, threaded
 *                        through because it is computed incrementally per 1s tick.
 * @param maxDigestingCount Caller-tracked peak simultaneous digesting count
 *                        across all test modes, computed per 1s tick.
 */
export function computeAggregateStats(
  sessions: ThreadSession[],
  nowMs: number = 0,
  maxStableCount: number | null = null,
  maxDigestingCount: number = 0,
): AggregateStats {
  // Include sessions with recorded tps_history OR sessions that completed before
  // the first 1s tick fired (closed with no history but with valid timing data).
  // For throughput sessions, also accept pub_start_ms as a timing anchor when
  // digest_start_ms is absent (e.g. sessions from before the digesting-patch fix).
  // Exclude suspicious (out-of-sync) sessions from the audit.
  const active = sessions.filter(
    (s) =>
      !isSessionSuspicious(s, nowMs) &&
      (
        (s.tps_history != null && s.tps_history.length > 0) ||
        (s.digest_start_ms != null && s.last_token_ms != null && s.tokens > 0) ||
        (s.pub_start_ms != null && s.last_token_ms != null && s.tokens > 0)
      ),
  );

  if (active.length === 0) {
    return {
      peakSumConcurrent: null,
      peakSingleStream: null,
      aveConcurrent: null,
      maxFirstTokenLatencyMs: null,
      sampleCount: 0,
      maxStableCount,
      maxDigestingCount,
    };
  }

  // Resolve each session's digest start epoch-ms for alignment.
  const startTimes = active.map(
    (s) => s.digest_start_ms ?? s.pub_start_ms ?? s.start_ms,
  );
  const minStartMs = Math.min(...startTimes);

  // Build aligned bucket map: global_second_offset → sum of all stream tokens.
  const bucketSums = new Map<number, number>();
  let peakSingleStream = 0;

  // Sub-second threshold: digest duration must be at least 100 ms (one 100ms
  // flush-tick interval) before we trust it for a per-second rate synthesis.
  // When first-token and last-token share the same JS timestamp (single-batch
  // delivery), digestMs == 0 → the old Math.max(1, digestMs) clamped to 1 ms
  // producing rates like tokens × 1000 — orders-of-magnitude too large.
  const SUB_SEC_MIN_MS = 100;

  // Indices of sessions whose tps_history is absent AND digest duration is too
  // short to synthesize reliably.  Filled in pass-1; resolved in pass-2.
  const deferredIndices: number[] = [];

  for (let i = 0; i < active.length; i++) {
    // Resolve per-session histogram.
    // • tps_history present → use directly (1 s tick measured, most accurate).
    // • tps_history absent, digestMs >= SUB_SEC_MIN_MS → synthesize 1 bucket.
    // • tps_history absent, digestMs < SUB_SEC_MIN_MS → defer to pass-2.
    const hist: number[] | null = (() => {
      const h = active[i].tps_history;
      if (h && h.length > 0) return h;
      const digestMs = active[i].last_token_ms! - active[i].digest_start_ms!;
      if (digestMs >= SUB_SEC_MIN_MS) {
        return [Math.round(active[i].tokens / (digestMs / 1000))];
      }
      return null; // unreliable — defer
    })();

    if (hist === null) {
      deferredIndices.push(i);
      continue;
    }

    // Round to nearest second to absorb small sub-second jitter in start times.
    const offset = Math.round((startTimes[i] - minStartMs) / 1000);
    for (let t = 0; t < hist.length; t++) {
      const bucket = offset + t;
      bucketSums.set(bucket, (bucketSums.get(bucket) ?? 0) + hist[t]);
      if (hist[t] > peakSingleStream) peakSingleStream = hist[t];
    }
  }

  // If no session produced reliable data (all deferred), return null metrics
  // so the header shows "—" rather than a fabricated number.
  const sums = Array.from(bucketSums.values());
  const peakSumConcurrent = sums.length > 0 ? Math.max(...sums) : null;
  const peakSingleStreamVal = peakSingleStream > 0 ? peakSingleStream : null;
  const aveConcurrent =
    sums.length > 0
      ? Math.round(sums.reduce((a, b) => a + b, 0) / sums.length)
      : null;

  // Max first-token latency: max(digest_start_ms - start_ms) across all sessions
  // that have a digest_start_ms (i.e. have received at least one token batch).
  const latencies = sessions
    .filter((s) => s.digest_start_ms != null)
    .map((s) => s.digest_start_ms! - s.start_ms);
  const maxFirstTokenLatencyMs = latencies.length > 0 ? Math.max(...latencies) : null;

  return {
    peakSumConcurrent,
    peakSingleStream: peakSingleStreamVal,
    aveConcurrent,
    maxFirstTokenLatencyMs,
    sampleCount: active.length,
    maxStableCount,
    maxDigestingCount,
  };
}
