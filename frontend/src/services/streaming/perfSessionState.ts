/**
 * Mutable per-session closure state for perf-test SSE sessions.
 *
 * All variables that were previously scattered as local `let` declarations
 * inside the `openSessionStream` callback are consolidated here so they can
 * be passed by reference to the handler factories in other modules.
 */

import type { DoneConditionGuard } from "./lifecycle";
import type { ThreadSession } from "../../components/StreamingPerfTestPanel/types";

/** All mutable per-session closure state, consolidated into one object. */
export interface SessionClosureState {
  sessionClosed: boolean;
  lastTokenLogPct: number;
  /**
   * Closure-tracked session status — mirrors React state for this session
   * so handlers can compute status transitions without reading stale React state.
   * Updated in onQueryStatus and when onTokenBatch promotes the session to "digesting".
   */
  sessionStatus: ThreadSession["status"];
  /**
   * Closure-tracked stream identifier — set when the `started` Centrifugo event
   * fires and carries the backend-assigned stream_id.  Null until that event
   * arrives.  Used to guard closeSession and terminal handlers against stale
   * events from a previous run on the same thread channel.
   */
  stream_id: string | null;
  /**
   * Closure-tracked first-token timestamp.  Set on the first token batch so
   * the pending patch always carries the authoritative digest_start_ms value
   * regardless of how many batches have been buffered.
   */
  closureDigestStartMs: number | null;
  /** Running total of tokens received for this session. */
  tokensReceived: number;
  /**
   * Backend-authoritative token count — updated from perf_test_complete,
   * perf_test_stopped, and completed(mock_pub) events.  May be less than
   * config.tokenCount when the backend's ingest phase timed out early.
   */
  actualTokensExpected: number;
  /**
   * Two-channel race guard: set when a completion event arrives before all
   * tokens are counted.  onTokenBatch calls terminate once the count is satisfied.
   */
  pendingComplete: boolean;
  pendingTerminalStatus: ThreadSession["status"];
  /** DoneConditionGuard for the drain-window phase. */
  doneGuard: DoneConditionGuard | null;
  /** Batch-size statistics tracked synchronously in the closure. */
  batchFirst: number | undefined;
  batchMax: number;
  batchSum: number;
  batchCount: number;
  /** EventSource cleanup ref — used by dequeue() to close the connection early. */
  esCleanup: (() => void) | null;
}

/** Create the initial mutable closure state for a new perf-test session. */
export function createSessionClosureState(initialTokenCount: number): SessionClosureState {
  return {
    sessionClosed: false,
    lastTokenLogPct: -1,
    sessionStatus: "connecting",
    stream_id: null,
    closureDigestStartMs: null,
    tokensReceived: 0,
    actualTokensExpected: initialTokenCount,
    pendingComplete: false,
    pendingTerminalStatus: "completed",
    doneGuard: null,
    batchFirst: undefined,
    batchMax: 0,
    batchSum: 0,
    batchCount: 0,
    esCleanup: null,
  };
}
