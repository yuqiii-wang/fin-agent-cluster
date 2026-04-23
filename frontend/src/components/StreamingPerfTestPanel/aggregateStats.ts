import type { ThreadSession } from "./types";

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
}

/**
 * Compute aggregate throughput statistics from an array of perf-test sessions.
 *
 * Only sessions that have at least one entry in `tps_history` are included.
 *
 * Alignment: each session's history is pinned to its `digest_start_ms`
 * (falling back to `pub_start_ms` then `start_ms`) so concurrent streams are
 * correctly summed by wall-clock second rather than by relative offset.
 */
export function computeAggregateStats(sessions: ThreadSession[]): AggregateStats {
  const active = sessions.filter(
    (s) => s.tps_history != null && s.tps_history.length > 0,
  );

  if (active.length === 0) {
    return {
      peakSumConcurrent: null,
      peakSingleStream: null,
      aveConcurrent: null,
      maxFirstTokenLatencyMs: null,
      sampleCount: 0,
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

  for (let i = 0; i < active.length; i++) {
    const hist = active[i].tps_history!;
    // Round to nearest second to absorb small sub-second jitter in start times.
    const offset = Math.round((startTimes[i] - minStartMs) / 1000);

    for (let t = 0; t < hist.length; t++) {
      const bucket = offset + t;
      bucketSums.set(bucket, (bucketSums.get(bucket) ?? 0) + hist[t]);
      if (hist[t] > peakSingleStream) peakSingleStream = hist[t];
    }
  }

  const sums = Array.from(bucketSums.values());
  const peakSumConcurrent = Math.max(...sums);
  const aveConcurrent = Math.round(sums.reduce((a, b) => a + b, 0) / sums.length);

  // Max first-token latency: max(digest_start_ms - start_ms) across all sessions
  // that have a digest_start_ms (i.e. have received at least one token batch).
  const latencies = sessions
    .filter((s) => s.digest_start_ms != null)
    .map((s) => s.digest_start_ms! - s.start_ms);
  const maxFirstTokenLatencyMs = latencies.length > 0 ? Math.max(...latencies) : null;

  return {
    peakSumConcurrent,
    peakSingleStream,
    aveConcurrent,
    maxFirstTokenLatencyMs,
    sampleCount: active.length,
  };
}
