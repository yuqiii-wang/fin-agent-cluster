import { useCallback } from "react";
import type React from "react";
import { ackQuery, openSseStream, openTokenStream } from "../../api";
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
        thread_id, cleanups, timeouts, userToken, config, patch, closeSession,
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

      // Gated ACK: hold the query ACK until the token stream subscription is
      // confirmed.  The backend starts ingest immediately after ACK, so we must
      // ensure the token channel is subscribed before any token_batch events are
      // published — otherwise early batches are published before the WS
      // subscription opens and are permanently lost (no history recovery).
      let _ackQueryReceived = false;
      let _ackConfirmed = false;
      let _ackInFlight = false;
      let _tokenStreamReady = false;

      const _tryAck = () => {
        if (_ackConfirmed || _ackInFlight || !_ackQueryReceived || !_tokenStreamReady) return;
        _ackInFlight = true;
        ackQuery(thread_id, userToken)
          .catch((err) => console.warn("[perf] ACK failed thread_id=%s", thread_id, err))
          .finally(() => { _ackInFlight = false; });
      };

      const onQueryReceived = () => { _ackQueryReceived = true; _tryAck(); };
      const onQueryAckConfirmed = () => { _ackConfirmed = true; };
      const onTokenStreamSubscribed = () => {
        _tokenStreamReady = true;
        console.info("[perf] token stream subscribed — releasing ACK gate thread_id=%s", thread_id);
        _tryAck();
      };

      const closeSse = openSseStream(thread_id, userToken, {
        onQueryReceived,
        onQueryAckConfirmed,
        onQueryStatus,
        onIngestComplete,
        onStarted,
        onCompleted,
        onStreamStopped,
        onStreamComplete,
        onDone,
        onFailed,
        onCancelled,
        onClose,
      });
      const closeToken = openTokenStream(thread_id, userToken, { onTokenBatch, onSubscribed: onTokenStreamSubscribed });
      const cleanup = () => { closeSse(); closeToken(); };

      // Register cleanup for freezeAll; armSafetyTimeout handles the last-resort timer.
      // helpers.dequeue() removes both when a terminal event fires.
      state.esCleanup = cleanup;
      cleanups.current.set(thread_id, cleanup);
      // 5 s buffer beyond the backend timeout so the safety timer fires only after
      // the backend has had time to complete and Centrifugo has delivered events.
      helpers.armSafetyTimeout((config.timeoutSecs + 5) * 1_000);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [patch, setSessions, closeSession, cleanups, timeouts, config.timeoutSecs, config.tokenCount, config.testMode, freezeAllRef, totalTokensRef, userToken],
  );

  return { openSessionStream };
}
