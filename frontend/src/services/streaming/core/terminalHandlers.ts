/**
 * Terminal SSE lifecycle event handlers for perf-test sessions.
 *
 * createTerminalHandlers returns six handlers that drive the session to a
 * final closed state.  All handlers delegate to terminate(), which is
 * idempotent — whichever event fires first wins; later events are no-ops.
 *
 *   onStreamStopped  — perf_test_stopped: concurrency timeout or early stop
 *   onStreamComplete — perf_test_complete: all tokens ingested + published
 *   onDone           — backend `done` signal; handles two-channel race via
 *                      activateDrainGuard when pendingComplete is set
 *   onFailed         — task failed; captures error message
 *   onCancelled      — user-initiated cancel confirmed
 *   onClose          — unexpected EventSource closure
 */

import type { SessionClosureState } from "./sessionState";
import type { PerfTestConfig, ThreadSession } from "../../../components/StreamingPerfTestPanel/types";
import { TERMINAL_STATUSES } from "../../../components/StreamingPerfTestPanel/types";
import type { SessionHelpers } from "./sessionHelpers";

export interface TerminalHandlerDeps {
  thread_id: string;
  config: Pick<PerfTestConfig, "testMode">;
  patch: (thread_id: string, delta: Partial<ThreadSession>) => void;
}

/**
 * Factory for SSE terminal lifecycle event handlers.
 * Handlers share SessionClosureState and SessionHelpers so each handler can
 * read and mutate the same in-flight state without closure staleness.
 */
export function createTerminalHandlers(
  state: SessionClosureState,
  deps: TerminalHandlerDeps,
  helpers: SessionHelpers,
) {
  const { thread_id, config, patch } = deps;
  const { terminate, activateDrainGuard, probeBackend } = helpers;

  const onStreamStopped = (data: unknown): void => {
    const d = data as { stream_id?: string; node_id?: string; duration_secs?: number; total_published?: number; ingest_ms?: number };
    // Reject stale events from a previous run on the same thread channel.
    if (d.stream_id && state.stream_id && d.stream_id !== state.stream_id) {
      console.warn(
        "[perf] perf_test_stopped stream_id mismatch — dropping stale event thread_id=%s event_stream=%s closure_stream=%s",
        thread_id, d.stream_id, state.stream_id,
      );
      return;
    }
    // Use the backend's authoritative published count if provided.
    if (d.total_published != null && d.total_published > 0) {
      state.actualTokensExpected = d.total_published;
    }
    if (d.ingest_ms != null && d.ingest_ms > 0) {
      patch(thread_id, { ingest_ms: d.ingest_ms, ingest_status: "completed" });
    }
    console.info(
      "[perf] perf_test_stopped %s total_published=%d tokens_received=%d actualExpected=%d",
      thread_id, d.total_published ?? 0, state.tokensReceived, state.actualTokensExpected,
    );
    if (config.testMode === "throughput" && state.tokensReceived < state.actualTokensExpected) {
      // Backend stopped before client received all published tokens — defer
      // terminate until onTokenBatch delivers the remaining ones.
      state.pendingComplete = true;
      state.pendingTerminalStatus = "timeout";
      console.warn(
        "[perf] perf_test_stopped deferred: received=%d expected=%d gap=%d thread_id=%s",
        state.tokensReceived, state.actualTokensExpected, state.actualTokensExpected - state.tokensReceived, thread_id,
      );
      probeBackend("perf_test_stopped_deferred");
      return;
    }
    // For concurrency mode the backend always emits perf_test_stopped before
    // done, so onDone will be a no-op (sessionClosed=true).
    const concurrencyStopped = config.testMode === "concurrency";
    terminate("timeout", /* ackDone */ concurrencyStopped);
  };

  const onStreamComplete = (data: unknown): void => {
    const d = data as { stream_id?: string; node_id?: string; total_tokens?: number; tps?: number; ingest_ms?: number };
    // Reject stale events from a previous run on the same thread channel.
    if (d.stream_id && state.stream_id && d.stream_id !== state.stream_id) {
      console.warn(
        "[perf] perf_test_complete stream_id mismatch — dropping stale event thread_id=%s event_stream=%s closure_stream=%s",
        thread_id, d.stream_id, state.stream_id,
      );
      return;
    }
    if (d.total_tokens != null && d.total_tokens > 0) {
      state.actualTokensExpected = d.total_tokens;
    }
    if (d.ingest_ms != null && d.ingest_ms > 0) {
      patch(thread_id, { ingest_ms: d.ingest_ms, ingest_status: "completed" });
    }
    console.info(
      "[perf] perf test complete %s tokens_received=%d actualExpected=%d",
      thread_id, state.tokensReceived, state.actualTokensExpected,
    );
    // Guard against the two-channel race: Redis Pub/Sub arrives before the
    // last Redis Stream token batches.
    if (config.testMode === "throughput" && state.tokensReceived < state.actualTokensExpected) {
      state.pendingComplete = true;
      state.pendingTerminalStatus = "completed";
      console.info(
        "[perf] perf_test_complete early arrival — awaiting %d tokens thread_id=%s",
        state.actualTokensExpected - state.tokensReceived, thread_id,
      );
      probeBackend("perf_test_complete_early");
      return;
    }
    const concurrencyComplete = config.testMode === "concurrency";
    terminate("completed", /* ackDone */ concurrencyComplete);
  };

  const onDone = (data: unknown): void => {
    const { status } = data as { status: string };
    console.info(
      "[perf] done %s status=%s tokens_received=%d actualExpected=%d",
      thread_id, status, state.tokensReceived, state.actualTokensExpected,
    );
    if (state.tokensReceived === 0) {
      console.error(
        "[perf] AUDIT ZERO-TOKENS done thread_id=%s — Centrifugo consumer may not be delivering fin:llm:tokens entries. " +
        "Check: (1) backend restarted with method=publish fix, (2) docker logs centrifugo-0 for consumer errors, " +
        "(3) redis XINFO GROUPS fin:llm:tokens for lag",
        thread_id,
      );
    }
    if (state.sessionClosed) return;
    const finalStatus = TERMINAL_STATUSES.has(status as ThreadSession["status"])
      ? (status as ThreadSession["status"])
      : "completed";
    // pendingComplete was set by onStreamComplete / onStreamStopped: tokens
    // haven't all arrived yet.  Activate drain guard so EventSource stays open
    // until onTokenBatch satisfies the count, or the 3-second window expires.
    if (state.pendingComplete) {
      console.warn(
        "[perf] done with pendingComplete — gap=%d, activating drain guard thread_id=%s",
        state.actualTokensExpected - state.tokensReceived, thread_id,
      );
      probeBackend("done_with_pending_complete");
      activateDrainGuard(state.pendingTerminalStatus);
      return;
    }
    if (finalStatus === "completed" && config.testMode === "throughput" && state.tokensReceived < state.actualTokensExpected) {
      // `done` arrived before perf_test_complete with tokens still in flight.
      state.pendingComplete = true;
      state.pendingTerminalStatus = "completed";
      console.info(
        "[perf] done early arrival — activating drain guard gap=%d thread_id=%s",
        state.actualTokensExpected - state.tokensReceived, thread_id,
      );
      probeBackend("done_early");
      activateDrainGuard("completed");
      return;
    }
    if (finalStatus !== "completed" && config.testMode === "throughput" && state.tokensReceived < state.actualTokensExpected) {
      console.warn(
        "[perf] short close on done: status=%s received=%d expected=%d gap=%d",
        finalStatus, state.tokensReceived, state.actualTokensExpected, state.actualTokensExpected - state.tokensReceived,
      );
      probeBackend(`done_${finalStatus}`);
    }
    terminate(finalStatus, /* ackDone */ true);
  };

  const onFailed = (data: unknown): void => {
    const errMsg =
      (data as { message?: string; error?: string })?.message ??
      (data as { message?: string; error?: string })?.error ??
      "Stream failed";
    console.warn("[perf] failed %s error=%s", thread_id, errMsg);
    patch(thread_id, { error: errMsg });
    // failed/cancelled are terminal task events but not `done`-path;
    // backend will still emit `done` after these, but sessionClosed will
    // be true by then so the `done` handler becomes a no-op.
    terminate("failed");
  };

  const onCancelled = (): void => {
    console.info("[perf] cancelled confirmed %s", thread_id);
    terminate("cancelled");
  };

  const onClose = (): void => {
    if (!state.sessionClosed) {
      state.sessionClosed = true;
      console.warn("[perf] connection closed unexpectedly %s", thread_id);
      patch(thread_id, { status: "failed", error: "Connection closed unexpectedly", closed: true });
    }
  };

  return { onStreamStopped, onStreamComplete, onDone, onFailed, onCancelled, onClose };
}
