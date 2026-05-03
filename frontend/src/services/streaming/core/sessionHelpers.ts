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

export interface SessionHelperDeps {
  thread_id: string;
  cleanups: React.MutableRefObject<Map<string, () => void>>;
  timeouts: React.MutableRefObject<Map<string, ReturnType<typeof setTimeout>>>;
  userToken: string;
  config: Pick<PerfTestConfig, "tokenCount">;
  closeSession: (thread_id: string, stream_id: string | null, finalStatus?: ThreadSession["status"]) => void;
}

export interface SessionHelpers {
  probeBackend: (reason: string) => void;
  dequeue: () => void;
  terminate: (finalStatus: ThreadSession["status"], ackDone?: boolean) => void;
  activateDrainGuard: (targetStatus: ThreadSession["status"]) => void;
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
  const { thread_id, cleanups, timeouts, userToken, config, closeSession } = deps;

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
      drainWindowMs: 3_000,
      conditions: [() => state.tokensReceived >= state.actualTokensExpected],
      onReady: (forced) => {
        console.info(
          "[perf] drain-guard resolved forced=%s status=%s gap=%d thread_id=%s",
          forced, targetStatus, state.actualTokensExpected - state.tokensReceived, thread_id,
        );
        terminate(targetStatus, /* ackDone */ true);
      },
    });
    state.doneGuard.trigger();
  };

  return { probeBackend, dequeue, terminate, activateDrainGuard };
}
