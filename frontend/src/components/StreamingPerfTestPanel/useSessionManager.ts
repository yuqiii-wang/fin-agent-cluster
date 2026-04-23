import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { cancelQuery, submitPerfQuery } from "../../api";

const PERF_TRIGGER = "DO STREAMING PERFORMANCE TEST NOW";
import type { PerfTestConfig, ThreadSession } from "./types";
import { usePerfSession } from "../../services/streaming";

interface UseSessionManagerReturn {
  sessions: ThreadSession[];
  totalTokens: number;
  activeCount: number;
  completedCount: number;
  /** True after the user clicked Complete — all controls are disabled. */
  frozen: boolean;
  handleAddRequest: (count: number) => Promise<void>;
  handleRestart: () => Promise<void>;
  handleComplete: () => void;
  handleCancelAll: () => void;
  handleCancelOne: (thread_id: string) => void;
}

export function useSessionManager(
  userToken: string,
  config: PerfTestConfig,
): UseSessionManagerReturn {
  const [sessions, setSessions] = useState<ThreadSession[]>([]);
  const cleanups = useRef<Map<string, () => void>>(new Map());
  const timeouts = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const labelCounter = useRef(1);
  const totalTokensRef = useRef(0);
  /** Ref mirror of config.tokenCount — used inside freezeAll without stale closure. */
  const tokenCountRef = useRef(config.tokenCount);
  /** Number of 100ms ticks elapsed (mod 10 drives the 1s sub-tick). */
  const centisTickRef = useRef(0);
  /** Per-session token snapshot at the last 1s tick — keyed by thread_id. */
  const prevSessionTokensRef = useRef<Map<string, number>>(new Map());
  const [frozen, setFrozen] = useState(false);

  // Refs so openSessionStream can call freezeAll without becoming stale —
  // avoids re-creating stream closures whenever sessions changes.
  const freezeAllRef = useRef<() => void>(() => {});
  // Track all thread_ids submitted on initial mount for StrictMode guard.
  const submittedIdsRef = useRef<string[]>([]);

  // Keep tokenCountRef in sync whenever config.tokenCount changes.
  useEffect(() => { tokenCountRef.current = config.tokenCount; }, [config.tokenCount]);

  const freezeAll = useCallback(() => {
    cleanups.current.forEach((fn) => fn());
    cleanups.current.clear();
    timeouts.current.forEach(clearTimeout);
    timeouts.current.clear();
    setSessions((prev) =>
      prev.map((s) => {
        if (s.closed) return s;
        // Only mark as completed if the stream actually received all its tokens.
        const finalStatus = s.tokens >= tokenCountRef.current ? "completed" as const : "cancelled" as const;
        return { ...s, status: finalStatus, closed: true };
      })
    );
    setFrozen(true);
  }, []);

  useEffect(() => { freezeAllRef.current = freezeAll; }, [freezeAll]);

  const patch = useCallback(
    (thread_id: string, delta: Partial<ThreadSession>) =>
      setSessions((prev) =>
        prev.map((s) => (s.thread_id === thread_id ? { ...s, ...delta } : s))
      ),
    [],
  );

  const closeSession = useCallback(
    (thread_id: string, finalStatus: ThreadSession["status"] = "cancelled") => {
      // Always clean up the EventSource and timeout, even if the session was
      // already marked closed (e.g. optimistic cancel patch).
      const cleanup = cleanups.current.get(thread_id);
      if (cleanup) { cleanup(); cleanups.current.delete(thread_id); }
      const tid = timeouts.current.get(thread_id);
      if (tid !== undefined) { clearTimeout(tid); timeouts.current.delete(thread_id); }
      // Only update status if the session was not already closed optimistically.
      // This prevents a backend `done` from overriding a user-initiated cancel
      // that was already reflected in the UI.
      setSessions((prev) =>
        prev.map((s) => {
          if (s.thread_id !== thread_id) return s;
          // If already closed (optimistic cancel), preserve existing status.
          if (s.closed) return s;
          return { ...s, status: finalStatus, closed: true };
        })
      );
    },
    [setSessions],
  );

  const { openSessionStream } = usePerfSession({
    cleanups,
    timeouts,
    config,
    patch,
    setSessions,
    closeSession,
    freezeAllRef,
    totalTokensRef,
    userToken,
  });

  // Ref guard: prevents React Strict Mode's double-effect from spawning a
  // second batch of 4 backend requests.  Refs survive the cleanup→remount
  // cycle that StrictMode performs in development.
  const didSpawnRef = useRef(false);

  /** Helper to build a fresh ThreadSession object. */
  const makeSession = useCallback(
    (thread_id: string, label: string, test_mode: "throughput" | "concurrency", start_ms: number): ThreadSession => ({
      thread_id,
      label,
      status: "connecting",
      tokens: 0,
      start_ms,
      last_token_ms: start_ms,
      last_token_text: "",
      closed: false,
      test_mode,
      tps_history: [],
    }),
    [],
  );

  useEffect(() => {
    const cleanup = () => {
      cleanups.current.forEach((fn) => fn());
      timeouts.current.forEach(clearTimeout);
    };

    if (didSpawnRef.current) {
      // StrictMode remount: all backend queries were already submitted; SSE
      // connections were closed by React's cleanup. Reset metrics and reopen
      // all previously submitted streams without duplicate backend queries.
      const now = Date.now();
      setSessions((prev) =>
        prev.map((s) => ({
          ...s,
          status: "connecting" as const,
          tokens: 0,
          start_ms: now,
          last_token_ms: now,
          last_token_text: "",
          closed: false,
        }))
      );
      submittedIdsRef.current.forEach((tid) => openSessionStream(tid));
      return cleanup;
    }
    didSpawnRef.current = true;
    submittedIdsRef.current = [];

    // Submit all initial streams: Stream #1 first (sequential so logs show
    // correct ordering), then the rest in parallel.
    const spawnAll = async () => {
      const count = config.initialRequestCount;

      // --- Stream #1 ---
      const firstLabelNum = labelCounter.current++;
      const firstLabel = `Stream #${firstLabelNum}`;
      const firstSpawnedAt = Date.now();
      let firstThreadId: string;
      try {
        const res = await submitPerfQuery(
          `${PERF_TRIGGER} - ${firstLabel}`,
          userToken,
          {
            perf_total_tokens: config.tokenCount,
            perf_timeout_secs: config.timeoutSecs,
            perf_test_mode: config.testMode,
            perf_token_per_sec: config.tokenPerSec,
          },
        );
        firstThreadId = res.thread_id;
        submittedIdsRef.current.push(firstThreadId);
        setSessions([makeSession(firstThreadId, firstLabel, config.testMode, firstSpawnedAt)]);
        console.info("[perf] stream #1 spawned thread_id=%s", firstThreadId);
        openSessionStream(firstThreadId);
      } catch (err) {
        console.error("[perf_panel] stream #1 spawn failed:", err);
        return;
      }

      // --- Streams #2 … #N in parallel ---
      if (count > 1) {
        await Promise.all(
          Array.from({ length: count - 1 }, async () => {
            try {
              const labelNum = labelCounter.current++;
              const label = `Stream #${labelNum}`;
              const spawnedAt = Date.now();
              const res = await submitPerfQuery(
                `${PERF_TRIGGER} - Stream #${labelNum}`,
                userToken,
                {
                  perf_total_tokens: config.tokenCount,
                  perf_timeout_secs: config.timeoutSecs,
                  perf_test_mode: config.testMode,
                  perf_token_per_sec: config.tokenPerSec,
                },
              );
              const thread_id = res.thread_id;
              submittedIdsRef.current.push(thread_id);
              setSessions((prev) => [...prev, makeSession(thread_id, label, config.testMode, spawnedAt)]);
              console.info("[perf] extra stream spawned thread_id=%s label=%s", thread_id, label);
              openSessionStream(thread_id);
            } catch (err) {
              console.error("[perf_panel] extra spawn failed:", err);
            }
          })
        );
      }
    };
    spawnAll();

    return cleanup;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleComplete = useCallback(() => {
    console.info("[perf] freeze triggered total_tokens=%d", totalTokensRef.current);
    freezeAll();
  }, [freezeAll]);

  const handleRestart = useCallback(async () => {
    console.info("[perf] restart triggered");
    // 1. Cancel backend streams for all currently active sessions.
    setSessions((prev) => {
      prev.forEach((s) => { if (!s.closed) cancelQuery(s.thread_id).catch(() => {}); });
      return prev;
    });
    // 2. Close all SSE connections and timers.
    cleanups.current.forEach((fn) => fn());
    cleanups.current.clear();
    timeouts.current.forEach(clearTimeout);
    timeouts.current.clear();
    // 3. Reset all tracking state.
    setFrozen(false);
    centisTickRef.current = 0;
    prevSessionTokensRef.current.clear();
    totalTokensRef.current = 0;
    setSessions([]);
    // Reset counters for a clean restart.
    labelCounter.current = 1;
    submittedIdsRef.current = [];
    // 4. Spawn config.initialRequestCount fresh concurrent streams.
    await Promise.all(
      Array.from({ length: config.initialRequestCount }, async () => {
        try {
          const labelNum = labelCounter.current++;
          const label = `Stream #${labelNum}`;
          const spawnedAt = Date.now();
          const res = await submitPerfQuery(
            `${PERF_TRIGGER} - Stream #${labelNum}`,
            userToken,
            {
              perf_total_tokens: config.tokenCount,
              perf_timeout_secs: config.timeoutSecs,
              perf_test_mode: config.testMode,
              perf_token_per_sec: config.tokenPerSec,
            },
          );
          const thread_id = res.thread_id;
          submittedIdsRef.current.push(thread_id);
          setSessions((prev) => [
            ...prev,
            makeSession(thread_id, label, config.testMode, spawnedAt),
          ]);
          console.info("[perf] restart stream spawned thread_id=%s label=%s", thread_id, label);
          openSessionStream(thread_id);
        } catch (err) {
          console.error("[perf_panel] restart spawn failed:", err);
        }
      })
    );
  }, [userToken, config, openSessionStream, makeSession]);

  const handleAddRequest = useCallback(async (count: number = 1) => {
    // If all streams finished and we were frozen (e.g. perf_test_stopped), unfreeze
    // so the interval tick and other controls resume correctly.
    if (frozen) setFrozen(false);
    console.info("[perf] adding %d request(s)", count);
    await Promise.all(
      Array.from({ length: count }, async () => {
        try {
          const labelNum = labelCounter.current++;
          const label = `Stream #${labelNum}`;
          const spawnedAt = Date.now();
          const res = await submitPerfQuery(
            `${PERF_TRIGGER} - Stream #${labelNum}`,
            userToken,
            {
              perf_total_tokens: config.tokenCount,
              perf_timeout_secs: config.timeoutSecs,
              perf_test_mode: config.testMode,
              perf_token_per_sec: config.tokenPerSec,
            },
          );
          const thread_id = res.thread_id;
          setSessions((prev) => [...prev, makeSession(thread_id, label, config.testMode, spawnedAt)]);
          console.info("[perf] add stream spawned thread_id=%s label=%s", thread_id, label);
          openSessionStream(thread_id);
        } catch (err) {
          console.error("[perf_panel] add request failed:", err);
        }
      }),
    );
  }, [userToken, config, openSessionStream, makeSession]);

  const handleCancelAll = useCallback(() => {
    console.info("[perf] cancel-all triggered active=%d", sessions.filter((s) => !s.closed).length);
    sessions.forEach((s) => {
      if (!s.closed) {
        // Optimistically show "cancelled" immediately; the EventSource stays open
        // until onCancelled (or onDone) fires from the backend and calls closeSession.
        patch(s.thread_id, { status: "cancelled", closed: true });
        cancelQuery(s.thread_id).catch(() => {});
      }
    });
  }, [sessions, patch]);

  const handleCancelOne = useCallback(
    (thread_id: string) => {
      console.info("[perf] cancel-one triggered thread_id=%s", thread_id);
      // Optimistically show "cancelled" immediately; the EventSource stays open
      // until onCancelled (or onDone) fires from the backend and calls closeSession.
      patch(thread_id, { status: "cancelled", closed: true });
      cancelQuery(thread_id).catch(() => {});
    },
    [patch],
  );

  const totalTokens = useMemo(() => sessions.reduce((acc, s) => acc + s.tokens, 0), [sessions]);
  const activeCount = useMemo(() => sessions.filter((s) => !s.closed).length, [sessions]);
  const completedCount = useMemo(() => sessions.filter((s) => s.status === "completed").length, [sessions]);

  useEffect(() => { totalTokensRef.current = totalTokens; }, [totalTokens]);

  const [, setTick] = useState(0);
  useEffect(() => {
    if (!activeCount) return;
    const iv = setInterval(() => {
      centisTickRef.current += 1;
      // ── 1 s sub-tick (every 10th 100 ms tick) ────────────────────────────────
      // TPS is measured over a 1-second window to avoid JS event-loop timer
      // jitter that inflates short windows: a late 100ms tick could appear to
      // carry 300ms worth of tokens, tripling the apparent rate.
      if (centisTickRef.current % 10 === 0) {
        // Append per-second TPS bucket only to sessions that are actively
        // sending tokens. Closed, completed, cancelled, failed, and
        // timeout sessions are excluded — their token count is frozen so the
        // delta would be 0 anyway, but more importantly we must not keep
        // growing their history after they are done.
        //
        // Also auto-advance browser-mode sessions that have received all tokens
        // to "completed" — the backend perf_test_complete / done event may lag
        // by up to one tick after the last perf_token_batch.
        setSessions((prev) =>
          prev.map((s) => {
            // Auto-complete: throughput mode reached 100% but backend event not yet arrived.
            // Concurrency mode sessions always end via timeout (perf_test_stopped).
            if (
              !s.closed &&
              config.testMode === "throughput" &&
              s.tokens >= config.tokenCount &&
              s.status !== "completed" && s.status !== "failed" &&
              s.status !== "cancelled" && s.status !== "timeout"
            ) {
              prevSessionTokensRef.current.delete(s.thread_id);
              return { ...s, status: "completed" as const, closed: true };
            }
            const sending = !s.closed && s.digest_start_ms != null &&
              (s.status === "digesting" || s.status === "running") &&
              s.tokens < config.tokenCount;
            if (!sending) {
              // Remove stale snapshot so the entry doesn't linger in the map.
              prevSessionTokensRef.current.delete(s.thread_id);
              return s;
            }
            // Use 0 as the initial baseline so the first bucket captures all tokens received since streaming started.
            const prevTok = prevSessionTokensRef.current.get(s.thread_id) ?? 0;
            const sessionDelta = Math.max(0, s.tokens - prevTok);
            prevSessionTokensRef.current.set(s.thread_id, s.tokens);
            return { ...s, tps_history: [...(s.tps_history ?? []), sessionDelta] };
          })
        );

      }

      // Always tick every 100ms so the Token Rate column (which reads Date.now()
      // dynamically in its render function) updates smoothly without waiting a
      // full second between refreshes.
      setTick((t) => t + 1);
    }, 100);
    return () => clearInterval(iv);
  }, [activeCount]);

  return {
    sessions,
    totalTokens,
    activeCount,
    completedCount,
    frozen,
    handleAddRequest,
    handleRestart,
    handleComplete,
    handleCancelAll,
    handleCancelOne,
  };
}
