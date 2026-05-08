/**
 * Core session-lifecycle helpers for perf-test SSE sessions.
 *
 * Factory createSessionHelpers returns four interdependent closures:
 *   probeBackend       — diagnostic log for unexpected session endings
 *   dequeue            — close EventSource + remove from cleanup/timeout maps
 *   terminate          — idempotent final close; optionally sends done-ACK
 *   activateDrainGuard — arm DoneConditionGuard for the two-channel race drain window
 *
 * All helpers mutate the shared SessionClosureState in place, which means
 * ordering and re-entrancy are safe: terminate() is guarded by sessionClosed,
 * and activateDrainGuard() is idempotent via the doneGuard null-check.
 */

import type React from "react";
import type { SessionClosureState } from "./sessionState";
import type { ThreadSession, PerfTestConfig } from "../../../components/StreamingPerfTestPanel/types";
import { DoneConditionGuard, sendDoneAck } from "./lifecycle";
import { cancelQuery } from "../../../api";

export interface SessionHelperDeps {
  thread_id: string;
  cleanups: React.MutableRefObject<Map<string, () => void>>;
  timeouts: React.MutableRefObject<Map<string, ReturnType<typeof setTimeout>>>;
  userToken: string;
  config: Pick<PerfTestConfig, "tokenCount" | "timeoutSecs" | "testMode">;
  patch: (thread_id: string, delta: Partial<ThreadSession>) => void;
  closeSession: (thread_id: string, stream_id: string | null, finalStatus?: ThreadSession["status"]) => void;
}

export interface SessionHelpers {
  probeBackend: (reason: string) => void;
  dequeue: () => void;
  terminate: (finalStatus: ThreadSession["status"], ackDone?: boolean) => void;
  activateDrainGuard: (targetStatus: ThreadSession["status"]) => void;
  /**
   * Arm the last-resort safety timeout for this session.
   * Registers a timer that fires after `timeoutMs` ms and, if the session is
   * still open, records a descriptive close_reason, sends a done-ACK, and
   * terminates with status="timeout".  dequeue() cancels the timer early when
   * a normal lifecycle terminal event fires first.
   */
  armSafetyTimeout: (timeoutMs: number) => void;
}

/**
 * Factory for the four core session-lifecycle helpers.
 * All helpers share a reference to the mutable SessionClosureState so they
 * always operate on current in-flight values without closure staleness.
 */
export function createSessionHelpers(
  state: SessionClosureState,
  deps: SessionHelperDeps,
): SessionHelpers {
  const { thread_id, cleanups, timeouts, userToken, config, patch, closeSession } = deps;

  const probeBackend = (reason: string): void => {
    console.warn(
      "[perf] session-ended reason=%s thread_id=%s tokens_received=%d tokens_expected=%d",
      reason, thread_id, state.tokensReceived, config.tokenCount,
    );
  };

  const dequeue = (): void => {
    state.esCleanup?.();
    state.esCleanup = null;
    cleanups.current.delete(thread_id);
    const tid = timeouts.current.get(thread_id);
    if (tid !== undefined) {
      clearTimeout(tid);
      timeouts.current.delete(thread_id);
    }
    if (state.lostTimer !== null) {
      clearTimeout(state.lostTimer);
      state.lostTimer = null;
    }
  };

  const terminate = (finalStatus: ThreadSession["status"], ackDone = false): void => {
    if (state.sessionClosed) return;
    state.sessionClosed = true;
    state.doneGuard?.cleanup();
    state.doneGuard = null;
    dequeue();
    if (ackDone) {
      sendDoneAck(thread_id, userToken, finalStatus).catch((err) => {
        console.warn("[perf] done-ack failed thread_id=%s", thread_id, err);
      });
    }
    closeSession(thread_id, state.stream_id, finalStatus);
  };

  const activateDrainGuard = (targetStatus: ThreadSession["status"]): void => {
    if (state.doneGuard) return; // already active
    state.doneGuard = new DoneConditionGuard({
      label: `perf:${thread_id}`,
      // Use the session timeout as the delivery drain window so the guard
      // is driven by config, not a hardcoded constant.  When the window
      // expires (forced=true), it means Centrifugo did not deliver all
      // tokens within the allowed period — use "timeout", not the original
      // targetStatus, so "completed" is never falsely reported.
      drainWindowMs: config.timeoutSecs * 1_000,
      conditions: [() => state.tokensReceived >= state.actualTokensExpected],
      onReady: (forced) => {
        const finalStatus =
          forced && state.tokensReceived < state.actualTokensExpected
            ? ("timeout" as const)
            : targetStatus;
        console.info(
          "[perf] drain-guard resolved forced=%s status=%s→%s gap=%d thread_id=%s",
          forced, targetStatus, finalStatus,
          state.actualTokensExpected - state.tokensReceived, thread_id,
        );
        terminate(finalStatus, /* ackDone */ true);
      },
    });
    state.doneGuard.trigger();
  };

  const armSafetyTimeout = (timeoutMs: number): void => {
    const tid = setTimeout(() => {
      // Always attempt to cancel the backend query, even if already closed.
      cancelQuery(thread_id, "timeout").catch(() => {});
      if (state.sessionClosed) return;

      const received = state.tokensReceived;
      const expected = state.actualTokensExpected;
      let closeReason: string;
      if (received === 0) {
        closeReason =
          `No tokens received — session was stuck at \"${state.sessionStatus}\". ` +
          `Check: (1) Centrifugo event delivery, (2) fanout dispatch, (3) WebSocket history gap.`;
        console.error(
          "[perf] ZERO-TOKEN SAFETY-TIMEOUT: mode=%s status=%s stream_id=%s",
          config.testMode, state.sessionStatus, state.stream_id,
        );
      } else if (received < expected) {
        const gap = expected - received;
        closeReason =
          `Delivery incomplete — received ${received.toLocaleString()} of ${expected.toLocaleString()} tokens (gap: ${gap.toLocaleString()})`;
        console.warn(
          "[perf] safety-timeout: delivery-incomplete mode=%s received=%d expected=%d gap=%d stream_id=%s",
          config.testMode, received, expected, gap, state.stream_id,
        );
      } else {
        closeReason = `Lifecycle did not complete — status was \"${state.sessionStatus}\" at expiry`;
        console.warn(
          "[perf] safety-timeout: lifecycle-incomplete mode=%s status=%s tokens=%d stream_id=%s",
          config.testMode, state.sessionStatus, received, state.stream_id,
        );
      }

      state.closeReason = closeReason;
      patch(thread_id, { close_reason: closeReason });
      // terminate sends done-ACK so the backend logs this forced closure.
      terminate("timeout", /* ackDone */ true);
    }, timeoutMs);
    timeouts.current.set(thread_id, tid);
  };

  return { probeBackend, dequeue, terminate, activateDrainGuard, armSafetyTimeout };
}
