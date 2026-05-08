/**
 * Per-token-batch SSE event handler for perf-test sessions.
 *
 * createTokenHandler returns onTokenBatch, which handles `perf_token_batch`
 * events.  Instead of calling setSessions on every event, it writes into
 * pendingTokenPatchesRef for the 100ms tick in useSessionManager to flush
 * in a single setSessions call — keeping re-renders ≤ 10/sec even when
 * hundreds of streams run concurrently.
 *
 * Auto-complete logic (throughput mode):
 *   When tokensReceived >= actualTokensExpected the handler flushes the
 *   buffered patch synchronously and calls terminate().
 */

import type React from "react";
import type { SessionClosureState } from "./sessionState";
import type { PendingTokenPatch, PerfTestConfig, ThreadSession } from "../../../components/StreamingPerfTestPanel/types";
import type { SessionHelpers } from "./sessionHelpers";

export interface TokenHandlerDeps {
  thread_id: string;
  config: Pick<PerfTestConfig, "testMode" | "tokenCount">;
  patch: (thread_id: string, delta: Partial<ThreadSession>) => void;
  pendingTokenPatchesRef: React.MutableRefObject<Map<string, PendingTokenPatch>>;
  flushPendingForSession: (thread_id: string) => void;
}

/** Factory for the onTokenBatch SSE event handler. */
export function createTokenHandler(
  state: SessionClosureState,
  deps: TokenHandlerDeps,
  helpers: SessionHelpers,
) {
  const { thread_id, config, patch, pendingTokenPatchesRef, flushPendingForSession } = deps;
  const { terminate, probeBackend } = helpers;

  const onTokenBatch = (data: unknown): void => {
    // Guard: ignore token events after any terminal lifecycle event has fired.
    if (state.sessionClosed) return;
    const d = data as { count?: number; recent_tokens?: string[]; ingest_ms?: number };
    const count = d.count ?? 1;
    state.tokensReceived += count;

    if (state.tokensReceived === count) {
      console.info(
        "[perf] FIRST token batch thread_id=%s count=%d sessionStatus=%s",
        thread_id, count, state.sessionStatus,
      );
      // Cancel lost-detection timer — at least one token arrived.
      if (state.lostTimer !== null) {
        clearTimeout(state.lostTimer);
        state.lostTimer = null;
      }
    }

    // Capture ingest_ms embedded in the final batch by the Celery worker.
    if (d.ingest_ms != null && d.ingest_ms > 0) {
      patch(thread_id, {
        ingest_ms: d.ingest_ms,
        ingest_status: "completed",
        ingest_produced: state.tokensReceived,
      });
    }

    // Update batch stats synchronously in the closure.
    if (state.batchFirst === undefined) state.batchFirst = count;
    if (count > state.batchMax) state.batchMax = count;
    state.batchSum += count;
    state.batchCount += 1;
    const batchAve = Math.round(state.batchSum / state.batchCount);

    const now = Date.now();
    if (state.closureDigestStartMs === null) state.closureDigestStartMs = now;

    const recentTokens = d.recent_tokens ?? [];
    const stream_text = (state.tokensReceived > recentTokens.length ? "…\n" : "") + recentTokens.join("\n");

    // Self-transition to "digesting" on the first token batch for both modes:
    // - Concurrency: ingest and delivery are simultaneous; backend never emits digesting.
    // - Throughput: backend emits digesting AFTER all tokens are written to Redis Stream,
    //   but centrifugo-token may deliver batches before the digesting SSE arrives via
    //   centrifugo-sse, so the lifecycle event races against token delivery.
    const wasPreDigesting =
      (state.sessionStatus === "connecting" || state.sessionStatus === "received" ||
       state.sessionStatus === "preparing" || state.sessionStatus === "ingesting");
    if (wasPreDigesting) state.sessionStatus = "digesting";

    const isLastBatch = state.tokensReceived >= state.actualTokensExpected && config.testMode === "throughput";

    // Buffer into pending patch — NO setSessions call here.
    const existing = pendingTokenPatchesRef.current.get(thread_id);
    pendingTokenPatchesRef.current.set(thread_id, {
      tokensDelta: (existing?.tokensDelta ?? 0) + count,
      last_token_ms: now,
      first_token_ms: existing?.first_token_ms ?? state.closureDigestStartMs,
      batch_first: existing?.batch_first ?? state.batchFirst!,
      batch_max: state.batchMax,
      batch_ave: batchAve,
      batch_last: count,
      stream_text,
      status_transition: wasPreDigesting ? "digesting" : existing?.status_transition,
      forceTokensTotal: isLastBatch ? state.tokensReceived : existing?.forceTokensTotal,
    });

    if (isLastBatch) {
      const status = state.pendingComplete ? state.pendingTerminalStatus : "completed";
      console.info(
        "[perf] all tokens received %s tokensReceived=%d actualExpected=%d reactTokensLag=%s status=%s",
        thread_id, state.tokensReceived, state.actualTokensExpected,
        state.pendingComplete ? "(pendingComplete)" : "(normal)", status,
      );
      // Flush the buffered patch synchronously before closing so the final
      // token count reaches React state before closeSession sets closed=true.
      flushPendingForSession(thread_id);
      if (state.pendingComplete && state.doneGuard) {
        state.doneGuard.recheck();
      } else {
        terminate(status, /* ackDone */ state.pendingComplete);
      }
    } else if (config.testMode === "throughput") {
      // Log progress every 10% milestone.
      const pct = Math.floor((state.tokensReceived / state.actualTokensExpected) * 100);
      const milestone = pct - (pct % 10);
      if (milestone > state.lastTokenLogPct) {
        state.lastTokenLogPct = milestone;
        console.info(
          "[perf] token-rx %s %d%% (%d/%d) pending_complete=%s",
          thread_id, milestone, state.tokensReceived, state.actualTokensExpected, state.pendingComplete,
        );
      }
      if (state.pendingComplete && pct >= 95 && state.lastTokenLogPct < 95) {
        state.lastTokenLogPct = 95;
        console.warn(
          "[perf] pending-complete stall: received=%d expected=%d gap=%d thread_id=%s",
          state.tokensReceived, state.actualTokensExpected, state.actualTokensExpected - state.tokensReceived, thread_id,
        );
        probeBackend("pending_complete_95pct");
      }
    }
  };

  return { onTokenBatch };
}
