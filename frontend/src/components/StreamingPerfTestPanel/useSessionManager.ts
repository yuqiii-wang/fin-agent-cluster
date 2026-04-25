import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { cancelQuery, submitPerfQuery, stablePerfStream } from "../../api";
import { fetchStreamingStatus } from "../../api";

const PERF_TRIGGER = "DO STREAMING PERFORMANCE TEST NOW";
import type { PerfTestConfig, ThreadSession } from "./types";
import { TERMINAL_STATUSES } from "./types";
import { usePerfSession } from "../../services/streaming";

/**
 * Returns true when ≥ 20 % of the previous TPS-history buckets (excluding the
 * most recent 2 seconds) each exceed 90 % of the target `tokenPerSec`.
 *
 * Rule:
 *   1. Drop the last 2 history buckets (recent jitter / burst exclusion).
 *   2. Of the remaining buckets, count those with TPS > 0.9 × tokenPerSec.
 *   3. If that count / total ≥ 0.20 → stable.
 *
 * Requires at least 3 history entries (so that at least 1 remains after
 * excluding the 2 most recent).
 *
 * Exported so columns.tsx can use the same logic for the "(stable)" display hint.
 */
export function isSessionStable(
  tpsHistory: number[],
  tokenPerSec: number,
): boolean {
  if (tokenPerSec <= 0 || tpsHistory.length < 3) return false;
  const prevHistory = tpsHistory.slice(0, -2);
  const threshold = 0.9 * tokenPerSec;
  const above = prevHistory.filter((v) => v > threshold).length;
  return above / prevHistory.length >= 0.20;
}

/**
 * Determines whether a throughput-mode session should auto-terminate on the
 * current 1-second tick.
 *
 * Concurrency-mode completion is handled separately as a group condition in the
 * tick (all active concurrent streams must be stable simultaneously).
 */
function resolveAutoTerminal(
  s: ThreadSession,
  tokenCount: number,
): ThreadSession["status"] | null {
  if (s.test_mode === "throughput" && s.tokens >= tokenCount) {
    return "completed";
  }
  return null;
}

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
  /** Ref mirror of sessions state — readable inside the tick interval without stale closure. */
  const sessionsRef = useRef<ThreadSession[]>([]);
  /** Number of 100ms ticks elapsed (mod 10 drives the 1s sub-tick). */
  const centisTickRef = useRef(0);
  /** Per-session token snapshot at the last 1s tick — keyed by thread_id. */
  const prevSessionTokensRef = useRef<Map<string, number>>(new Map());
  const [frozen, setFrozen] = useState(false);

  /** Ref mirrors of config scalars — used inside setInterval/closeSession to avoid stale closures. */
  const tokenPerSecRef = useRef(config.tokenPerSec);
  const timeoutSecsRef = useRef(config.timeoutSecs);
  /** Tracks thread_ids for which a stable signal has already been sent to the backend. */
  const stableSignaledRef = useRef<Set<string>>(new Set());

  // Refs so openSessionStream can call freezeAll without becoming stale —
  // avoids re-creating stream closures whenever sessions changes.
  const freezeAllRef = useRef<() => void>(() => {});
  // Track all thread_ids submitted on initial mount for StrictMode guard.
  const submittedIdsRef = useRef<string[]>([]);

  // Keep tokenCountRef in sync whenever config.tokenCount changes.
  useEffect(() => { tokenCountRef.current = config.tokenCount; }, [config.tokenCount]);
  useEffect(() => { tokenPerSecRef.current = config.tokenPerSec; }, [config.tokenPerSec]);
  useEffect(() => { timeoutSecsRef.current = config.timeoutSecs; }, [config.timeoutSecs]);
  useEffect(() => { sessionsRef.current = sessions; }, [sessions]);

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
          // If already closed (optimistic cancel or tick auto-complete), preserve existing status.
          if (s.closed) return s;

          // Definitive timeout→completed upgrade for concurrency mode.
          // The backend always ends concurrency sessions with `perf_test_stopped` (timeout IS the
          // expected stop mechanism), so we check whether the session ran stably before accepting
          // "timeout" as the displayed status.  This guard covers the race where the backend SSE
          // event arrives before the tick fires the group-stability check.
          let resolvedStatus = finalStatus;
          if (finalStatus === "timeout" && s.test_mode === "concurrency") {
            if (isSessionStable(s.tps_history ?? [], tokenPerSecRef.current)) {
              resolvedStatus = "completed";
            }
          }

          console.info(
            "[perf] closeSession thread_id=%s finalStatus=%s tokens_in_state=%d",
            thread_id, resolvedStatus, s.tokens,
          );
          return { ...s, status: resolvedStatus, closed: true };
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
      stream_text: "",
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

    // Submit all initial streams in parallel.
    const spawnAll = async () => {
      const count = config.initialRequestCount;
      await Promise.all(
        Array.from({ length: count }, async () => {
          const labelNum = labelCounter.current++;
          const label = `Stream #${labelNum}`;
          const spawnedAt = Date.now();
          const tempId = `pending-${labelNum}`;
          setSessions((prev) => [...prev, makeSession(tempId, label, config.testMode, spawnedAt)]);
          try {
            const res = await submitPerfQuery(
              `${PERF_TRIGGER} - ${label}`,
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
            setSessions((prev) => prev.map((s) => s.thread_id === tempId ? { ...s, thread_id } : s));
            console.info("[perf] stream spawned thread_id=%s label=%s", thread_id, label);
            openSessionStream(thread_id);
          } catch (err) {
            console.error("[perf_panel] spawn failed:", err);
            setSessions((prev) => prev.map((s) => s.thread_id === tempId ? { ...s, status: "failed" as const, closed: true } : s));
          }
        })
      );
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
    stableSignaledRef.current.clear();
    totalTokensRef.current = 0;
    setSessions([]);
    // Reset counters for a clean restart.
    labelCounter.current = 1;
    submittedIdsRef.current = [];
    // 4. Spawn config.initialRequestCount fresh concurrent streams.
    await Promise.all(
      Array.from({ length: config.initialRequestCount }, async () => {
        const labelNum = labelCounter.current++;
        const label = `Stream #${labelNum}`;
        const spawnedAt = Date.now();
        const tempId = `pending-${labelNum}`;
        setSessions((prev) => [...prev, makeSession(tempId, label, config.testMode, spawnedAt)]);
        try {
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
          setSessions((prev) => prev.map((s) => s.thread_id === tempId ? { ...s, thread_id } : s));
          console.info("[perf] restart stream spawned thread_id=%s label=%s", thread_id, label);
          openSessionStream(thread_id);
        } catch (err) {
          console.error("[perf_panel] restart spawn failed:", err);
          setSessions((prev) => prev.map((s) => s.thread_id === tempId ? { ...s, status: "failed" as const, closed: true } : s));
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
        const labelNum = labelCounter.current++;
        const label = `Stream #${labelNum}`;
        const spawnedAt = Date.now();
        const tempId = `pending-${labelNum}`;
        setSessions((prev) => [...prev, makeSession(tempId, label, config.testMode, spawnedAt)]);
        try {
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
          setSessions((prev) => prev.map((s) => s.thread_id === tempId ? { ...s, thread_id } : s));
          console.info("[perf] add stream spawned thread_id=%s label=%s", thread_id, label);
          openSessionStream(thread_id);
        } catch (err) {
          console.error("[perf_panel] add request failed:", err);
          setSessions((prev) => prev.map((s) => s.thread_id === tempId ? { ...s, status: "failed" as const, closed: true } : s));
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
        if (!s.thread_id.startsWith("pending-")) {
          cancelQuery(s.thread_id).catch(() => {});
        }
      }
    });
  }, [sessions, patch]);

  const handleCancelOne = useCallback(
    (thread_id: string) => {
      console.info("[perf] cancel-one triggered thread_id=%s", thread_id);
      // Optimistically show "cancelled" immediately; the EventSource stays open
      // until onCancelled (or onDone) fires from the backend and calls closeSession.
      patch(thread_id, { status: "cancelled", closed: true });
      if (!thread_id.startsWith("pending-")) {
        cancelQuery(thread_id).catch(() => {});
      }
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
        // ── Concurrency stable signal ────────────────────────────────────────
        // Read sessions via ref (avoids stale closure) and send the backend
        // stable signal BEFORE setSessions so it is dispatched even when the
        // state update marks sessions as completed in this same tick.
        const activeConcurrentNow = sessionsRef.current.filter(
          (s) => !s.closed && !TERMINAL_STATUSES.has(s.status) &&
                 s.test_mode === "concurrency" && s.digest_start_ms != null,
        );
        if (activeConcurrentNow.length > 0) {
          const allStableNow = activeConcurrentNow.every(
            (s) => isSessionStable(s.tps_history ?? [], tokenPerSecRef.current),
          );
          if (allStableNow) {
            activeConcurrentNow.forEach((s) => {
              if (!stableSignaledRef.current.has(s.thread_id)) {
                stableSignaledRef.current.add(s.thread_id);
                console.info("[perf] stable → backend thread_id=%s", s.thread_id);
                stablePerfStream(s.thread_id)
                  .then(() => {
                    // Evidence: probe backend immediately after signalling to confirm
                    // whether the lifecycle has already ended or is still running.
                    fetchStreamingStatus(s.thread_id).then((probe) => {
                      console.info(
                        "[perf] stable-probe thread_id=%s query_status=%s is_active=%s " +
                        "last_token_ms_ago=%s running_tasks=%s",
                        s.thread_id,
                        probe.query_status,
                        probe.is_active,
                        probe.last_token_ms_ago == null ? "n/a" : `${probe.last_token_ms_ago}ms`,
                        probe.running_tasks.map((t) => t.task_key).join(",") || "none",
                      );
                    }).catch((e) =>
                      console.warn("[perf] stable-probe failed thread_id=%s", s.thread_id, e),
                    );
                  })
                  .catch((e) =>
                    console.warn("[perf] stable signal failed", s.thread_id, e),
                  );
              }
            });
          }
        }

        // Append per-second TPS bucket and evaluate auto-terminal conditions.
        //
        // Two-pass design:
        //   Pass 1 — accumulate: build the new tps_history for every active session
        //            (regardless of transient status bounces like "ingesting").
        //   Pass 2 — terminate:
        //     • Throughput sessions close individually once all tokens are delivered.
        //     • Concurrency sessions mark as "completed" (freezing the UI) as a GROUP
        //       once all are stable.  closed:true is NOT set here — the EventSource
        //       stays open to receive the backend perf_test_complete ack, which drives
        //       the final closeSession → closed:true transition.
        setSessions((prev) => {
          // ── Pass 1: accumulate TPS histories ──────────────────────────────────
          const withHistory = prev.map((s) => {
            if (s.closed || TERMINAL_STATUSES.has(s.status)) {
              prevSessionTokensRef.current.delete(s.thread_id);
              return s;
            }
            if (s.digest_start_ms == null) {
              // Streaming not started yet; keep snapshot untouched.
              return s;
            }
            const prevTok = prevSessionTokensRef.current.get(s.thread_id) ?? 0;
            const delta = Math.max(0, s.tokens - prevTok);
            prevSessionTokensRef.current.set(s.thread_id, s.tokens);
            return { ...s, tps_history: [...(s.tps_history ?? []), delta] };
          });

          // ── Pass 2: group stability check for concurrency ─────────────────────
          // If ALL active concurrency sessions are individually stable, close every
          // one as "completed" immediately (optimistic UI — backend signal also sent
          // by the useEffect below).
          const activeConcurrent = withHistory.filter(
            (s) => !s.closed && !TERMINAL_STATUSES.has(s.status) &&
                   s.test_mode === "concurrency" && s.digest_start_ms != null,
          );
          const concurrencyGroupStable =
            activeConcurrent.length > 0 &&
            activeConcurrent.every((s) =>
              isSessionStable(s.tps_history ?? [], tokenPerSecRef.current),
            );

          // ── Pass 2: apply terminal conditions ────────────────────────────────
          return withHistory.map((s) => {
            if (s.closed || TERMINAL_STATUSES.has(s.status)) return s;

            // Throughput: individual completion via tick.
            // Note: usePerfSession.onPerfTokenBatch also fires terminate() at 100%,
            // setting sessionClosed=true in the closure.  This tick path is a
            // belt-and-suspenders guard for the case where the EventSource already
            // closed cleanly and the session just needs React state to reflect completion.
            // It intentionally does NOT call dequeue() — the EventSource was already
            // closed by usePerfSession's terminate() when tokensReceived hit the target.
            if (s.test_mode === "throughput") {
              const terminalStatus = resolveAutoTerminal(s, tokenCountRef.current);
              if (terminalStatus !== null) {
                console.info(
                  "[perf] tick auto-complete thread_id=%s tokens=%d target=%d",
                  s.thread_id, s.tokens, tokenCountRef.current,
                );
                prevSessionTokensRef.current.delete(s.thread_id);
                return { ...s, status: terminalStatus, closed: true };
              }
              return s;
            }

            // Concurrency: freeze UI as "completed" once the whole group is stable.
            // closed:true is withheld so the EventSource remains open to receive the
            // backend perf_test_complete ack — that event drives closeSession → closed:true.
            if (s.test_mode === "concurrency" && concurrencyGroupStable) {
              console.info(
                "[perf] concurrency stable → completed (awaiting backend ack) thread_id=%s",
                s.thread_id,
              );
              prevSessionTokensRef.current.delete(s.thread_id);
              return { ...s, status: "completed" as const };
            }

            return s;
          });
        });

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
