import { useCallback } from "react";
import type React from "react";
import { cancelQuery, createAckHandlers, openStream } from "../../api";
import type { PendingTokenPatch, PerfTestConfig, ThreadSession } from "../../components/StreamingPerfTestPanel/types";
import {
  createSessionClosureState,
  createSessionHelpers,
  createPhaseHandlers,
  createTokenHandler,
  createTerminalHandlers,
} from "./core";

export interface PerfSessionDeps {
  cleanups: React.MutableRefObject<Map<string, () => void>>;
  timeouts: React.MutableRefObject<Map<string, ReturnType<typeof setTimeout>>>;
  config: PerfTestConfig;
  patch: (thread_id: string, delta: Partial<ThreadSession>) => void;
  setSessions: React.Dispatch<React.SetStateAction<ThreadSession[]>>;
  closeSession: (thread_id: string, stream_id: string | null, finalStatus?: ThreadSession["status"]) => void;
  freezeAllRef: React.MutableRefObject<() => void>;
  totalTokensRef: React.MutableRefObject<number>;
  /** Guest user token required to send the query ACK. */
  userToken: string;
  /**
   * Shared ref map for buffered token patches.  Instead of calling setSessions
   * on every `perf_token_batch` SSE event, onPerfTokenBatch writes into this map
   * and the 100ms tick in useSessionManager flushes them in a single setSessions
   * call.  This prevents hundreds of re-renders per second when many streams run
   * concurrently.
   */
  pendingTokenPatchesRef: React.MutableRefObject<Map<string, PendingTokenPatch>>;
  /**
   * Flush the buffered patch for a single session immediately.  Called by
   * onPerfTokenBatch's terminal path so the final token count is committed to
   * React state before closeSession sets closed=true.
   */
  flushPendingForSession: (thread_id: string) => void;
}

export interface UsePerfSessionReturn {
  /** Open the SSE stream for a single session. */
  openSessionStream: (thread_id: string) => void;
}

/**
 * Thin orchestrator: assembles per-session state, helpers, and handlers,
 * then wires them into openStream.  All logic lives in the specialised
 * factory modules imported above.
 */
export function usePerfSession(deps: PerfSessionDeps): UsePerfSessionReturn {
  const {
    cleanups,
    timeouts,
    config,
    patch,
    setSessions,
    closeSession,
    freezeAllRef,
    totalTokensRef,
    userToken,
    pendingTokenPatchesRef,
    flushPendingForSession,
  } = deps;

  const openSessionStream = useCallback(
    (thread_id: string) => {
      const state = createSessionClosureState(config.tokenCount);

      const helpers = createSessionHelpers(state, {
        thread_id, cleanups, timeouts, userToken, config, closeSession,
      });

      const { onQueryStatus, onIngestComplete, onStarted, onCompleted } =
        createPhaseHandlers(state, { thread_id, userToken, patch, setSessions, config });

      const { onTokenBatch } = createTokenHandler(
        state,
        { thread_id, config, patch, pendingTokenPatchesRef, flushPendingForSession },
        helpers,
      );

      const { onStreamStopped, onStreamComplete, onDone, onFailed, onCancelled, onClose } =
        createTerminalHandlers(state, { thread_id, config, patch }, helpers);

      console.info("[perf] opening stream thread_id=%s", thread_id);

      const cleanup = openStream(thread_id, userToken, {
        ...createAckHandlers(thread_id, userToken, "perf"),
        onQueryStatus,
        onIngestComplete,
        onStarted,
        onCompleted,
        onTokenBatch,
        onStreamStopped,
        onStreamComplete,
        onDone,
        onFailed,
        onCancelled,
        onClose,
      });

      // Register cleanup for freezeAll and the last-resort safety timeout.
      // helpers.dequeue() removes both when a terminal event fires.
      state.esCleanup = cleanup;
      cleanups.current.set(thread_id, cleanup);
      // Add 5 s buffer beyond the backend timeout so the safety timer fires
      // only after the backend has had time to complete and Centrifugo has
      // delivered the final stream_stopped event.
      const sessionTimeoutMs = (config.timeoutSecs + 5) * 1000;
      const tid = setTimeout(() => {
        if (!state.sessionClosed) {
          state.sessionClosed = true;
          helpers.dequeue();
          const logLevel = state.tokensReceived === 0 ? "error" : "warn";
          console[logLevel](
            "[perf] safety-timeout fired: mode=%s status=%s tokens=%d stream_id=%s",
            config.testMode, state.sessionStatus, state.tokensReceived, state.stream_id,
          );
          if (state.tokensReceived === 0) {
            console.error(
              "[perf] ZERO-TOKEN TIMEOUT — session never advanced past status=%s. " +
              "Possible causes: (1) ingesting phase event dropped by Centrifugo, " +
              "(2) session not dispatched in fanout batch, " +
              "(3) WebSocket delivery gap with no history replay. stream_id=%s",
              state.sessionStatus, state.stream_id,
            );
          }
          if (config.testMode === "throughput" && state.tokensReceived < config.tokenCount) {
            helpers.probeBackend("safety_timeout");
          }
          closeSession(thread_id, state.stream_id, "timeout");
        }
        cancelQuery(thread_id, "timeout").catch(() => {});
      }, sessionTimeoutMs);
      timeouts.current.set(thread_id, tid);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [patch, setSessions, closeSession, cleanups, timeouts, config.timeoutSecs, config.tokenCount, config.testMode, freezeAllRef, totalTokensRef, userToken],
  );

  return { openSessionStream };
}
