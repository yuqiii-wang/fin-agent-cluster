/**
 * useTokenBatchFlush — token_batch event buffering for concurrency-mode streaming tasks.
 *
 * Exposes:
 *   onTokenBatch  — Centrifugo event handler; writes into refs, never calls setSessions.
 *   drainBatch    — called by the host's 100ms flush interval; returns pending data + clears refs.
 *   resetBatch    — clears all refs and cumulative totals (call on session reset).
 *
 * Uses SET semantics per task (not append).  recent_tokens is a rolling deque(maxlen=10)
 * from the backend — each batch replaces the display text rather than extending it.
 * Mirrors the stream_text formula in tokenHandler.ts:
 *
 *   stream_text = (total > recent_tokens.length ? "…\n" : "") + recent_tokens.join("\n")
 */

import { useCallback, useRef } from "react";

export interface DrainedBatch {
  /** Latest stream text per task_id (SET semantics — replace, not append). */
  streams: Record<string, string>;
  /** Token count delta per task_id to add to the cumulative count. */
  counts: Record<string, number>;
}

export interface UseTokenBatchFlushReturn {
  /**
   * Centrifugo `token_batch` event handler.  Reads task_id, count, recent_tokens
   * and updates the internal replace-refs.  Never touches React state.
   */
  onTokenBatch: (data: unknown) => void;
  /**
   * Drain all buffered patches and clear refs.
   * Returns null when nothing has accumulated since the last drain.
   * Call this inside the host's 100ms setInterval flush.
   */
  drainBatch: () => DrainedBatch | null;
  /**
   * Reset all refs and cumulative totals.  Call when the host session resets.
   */
  resetBatch: () => void;
}

/**
 * Manages per-task token_batch buffering for concurrency-mode streaming tasks.
 *
 * The hook exposes a drain-based API so the host (useSingleTestSession) can
 * keep a single unified setInterval that handles both LLM onToken append-path
 * and concurrency onTokenBatch replace-path without duplicating flush logic.
 */
export function useTokenBatchFlush(): UseTokenBatchFlushReturn {
  /** Latest stream_text per task_id — SET on each batch (not appended). */
  const batchStreamReplaceRef = useRef<Record<string, string>>({});
  /** Count delta accumulated since last drain. */
  const batchCountDeltaRef = useRef<Record<string, number>>({});
  /** Cumulative tokens received per task — never reset between batches. */
  const batchTotalsRef = useRef<Record<string, number>>({});

  const onTokenBatch = useCallback((data: unknown): void => {
    const d = data as { task_id?: string; count?: number; recent_tokens?: string[] };
    const taskId = d.task_id;
    if (!taskId) return;
    const recentTokens = d.recent_tokens ?? [];
    const count = d.count ?? recentTokens.length;
    if (count === 0) return;

    batchTotalsRef.current[taskId] = (batchTotalsRef.current[taskId] ?? 0) + count;
    const total = batchTotalsRef.current[taskId];
    // Mirror tokenHandler.ts: "…\n" prefix when total exceeds the sliding window size.
    const stream_text =
      (total > recentTokens.length ? "…\n" : "") + recentTokens.join("\n");

    batchStreamReplaceRef.current[taskId] = stream_text;
    batchCountDeltaRef.current[taskId] =
      (batchCountDeltaRef.current[taskId] ?? 0) + count;
  }, []);

  const drainBatch = useCallback((): DrainedBatch | null => {
    const streams = batchStreamReplaceRef.current;
    const counts = batchCountDeltaRef.current;
    if (Object.keys(streams).length === 0) return null;
    batchStreamReplaceRef.current = {};
    batchCountDeltaRef.current = {};
    return { streams, counts };
  }, []);

  const resetBatch = useCallback((): void => {
    batchStreamReplaceRef.current = {};
    batchCountDeltaRef.current = {};
    batchTotalsRef.current = {};
  }, []);

  return { onTokenBatch, drainBatch, resetBatch };
}
