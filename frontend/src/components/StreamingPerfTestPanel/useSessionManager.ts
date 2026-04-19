import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { cancelQuery, openStream, submitQuery } from "../../api";
import type { PerfTestConfig, ThreadSession } from "./types";

interface UseSessionManagerReturn {
  sessions: ThreadSession[];
  totalTokens: number;
  activeCount: number;
  completedCount: number;
  avgTokenRate: number;
  perSecStats: { tps: number; peak: number };
  /** Wall-clock ms from fanout start to the last stream's done event. Null until all sessions close. */
  fanoutElapsedMs: number | null;
  /** True after the user clicked Complete — all controls are disabled. */
  frozen: boolean;
  handleAddRequest: (count: number) => Promise<void>;
  handleRestart: () => Promise<void>;
  handleComplete: () => void;
  handleStopAll: () => void;
  handleStopOne: (thread_id: string) => void;
}

export function useSessionManager(
  initialThreadId: string,
  userToken: string,
  config: PerfTestConfig,
): UseSessionManagerReturn {
  const [sessions, setSessions] = useState<ThreadSession[]>([]);
  const cleanups = useRef<Map<string, () => void>>(new Map());
  const timeouts = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const labelCounter = useRef(1);
  const totalTokensRef = useRef(0);
  const prevTotalRef = useRef(0);
  const [perSecStats, setPerSecStats] = useState({ tps: 0, peak: 0 });
  /** Timestamp when the fanout group was initialised (first session opened). */
  const fanoutStartMsRef = useRef<number>(Date.now());
  const [fanoutElapsedMs, setFanoutElapsedMs] = useState<number | null>(null);
  const fanoutCompleteSignalledRef = useRef(false);
  const fanoutCompletedCountRef = useRef(0);
  const sessionsRef = useRef<ThreadSession[]>([]);
  const [frozen, setFrozen] = useState(false);

  // Ref so openSessionStream (useCallback) can call freezeAll without becoming
  // stale — avoids re-creating stream closures whenever sessions changes.
  const freezeAllRef = useRef<() => void>(() => {});

  const freezeAll = useCallback(() => {
    cleanups.current.forEach((fn) => fn());
    cleanups.current.clear();
    timeouts.current.forEach(clearTimeout);
    timeouts.current.clear();
    setSessions((prev) => prev.map((s) => s.closed ? s : { ...s, status: "completed" as const, closed: true }));
    setFrozen(true);
  }, []);

  useEffect(() => { freezeAllRef.current = freezeAll; }, [freezeAll]);

  const patch = useCallback(
    (thread_id: string, delta: Partial<ThreadSession>) =>
      setSessions((prev) =>
        prev.map((s) => (s.thread_id === thread_id ? { ...s, ...delta } : s))
      ),
    []
  );

  const closeSession = useCallback(
    (thread_id: string, finalStatus: ThreadSession["status"] = "stopped") => {
      const cleanup = cleanups.current.get(thread_id);
      if (cleanup) { cleanup(); cleanups.current.delete(thread_id); }
      const tid = timeouts.current.get(thread_id);
      if (tid !== undefined) { clearTimeout(tid); timeouts.current.delete(thread_id); }
      patch(thread_id, { status: finalStatus, closed: true });
    },
    [patch]
  );

  const attachStream = useCallback(
    (thread_id: string, cleanup: () => void) => {
      cleanups.current.set(thread_id, cleanup);
      // Last-resort safety timeout: fires only if the SSE connection stays open
      // but neither perf_test_stopped nor done events arrive (e.g. silent
      // network partition).  Set to the backend's own deadline so the UI
      // self-heals exactly when the backend would have stopped anyway.
      // Normal termination cancels this via closeSession → clearTimeout.
      const sessionTimeoutMs = config.timeoutSecs * 1000;
      const tid = setTimeout(() => {
        cancelQuery(thread_id).catch(() => {});
        closeSession(thread_id, "completed");
      }, sessionTimeoutMs);
      timeouts.current.set(thread_id, tid);
    },
    [closeSession, config.timeoutSecs]
  );

  const openSessionStream = useCallback(
    (thread_id: string) => {
      patch(thread_id, { status: "running" });
      let sessionClosed = false;

      const cleanup = openStream(thread_id, {
        onStarted: (_data) => {
          // No watchTask needed: perf_token events are always forwarded
          // regardless of watch state, so token counting is unaffected by
          // the TaskDrawer open/close lifecycle.
        },
        onPerfToken: (_data) => {
          setSessions((prev) =>
            prev.map((s) => {
              if (s.thread_id !== thread_id) return s;
              return { ...s, tokens: s.tokens + 1, last_token_ms: Date.now() };
            })
          );
        },
        onPerfIngestProgress: (data) => {
          const d = data as { produced?: number; total_tokens?: number; ingest_tps?: number; status?: string };
          const isIngestDone = d.status === "completed" || d.status === "timeout";
          setSessions((prev) =>
            prev.map((s) => {
              if (s.thread_id !== thread_id) return s;
              return {
                ...s,
                ingest_produced: d.produced,
                ingest_total: d.total_tokens,
                ingest_tps: d.ingest_tps,
                ingest_status: (d.status === "running" || d.status === "completed" || d.status === "timeout")
                  ? d.status
                  : "running",
                // Set pub_start_ms the first time ingest finishes; never overwrite once set.
                pub_start_ms: s.pub_start_ms ?? (isIngestDone ? Date.now() : undefined),
              };
            })
          );
        },
        onCompleted: (data) => {
          // Handle ingest and pub phase completions individually.
          const d = data as { task_key?: string };
          const key = d?.task_key ?? "";
          if (key === "perf_test_streamer.mock_ingest") {
            patch(thread_id, { ingest_status: "completed", pub_start_ms: Date.now() });
            fanoutCompletedCountRef.current += 1;
            if (
              !fanoutCompleteSignalledRef.current &&
              fanoutCompletedCountRef.current >= sessionsRef.current.length
            ) {
              fanoutCompleteSignalledRef.current = true;
              setFanoutElapsedMs(Date.now() - fanoutStartMsRef.current);
            }
          } else if (key === "perf_test_streamer.mock_pub") {
            patch(thread_id, { pub_status: "completed" });
          }
        },
        onPerfTestStopped: (_data) => {
          // Timeout fired — force-set fanout elapsed if not yet captured
          // (timeout fired before all tokens were produced).
          if (!fanoutCompleteSignalledRef.current) {
            fanoutCompleteSignalledRef.current = true;
            setFanoutElapsedMs(Date.now() - fanoutStartMsRef.current);
          }
          console.info(
            "[perf_panel] perf_test_stopped: perf_token count at timeout=%d",
            totalTokensRef.current,
          );
          sessionClosed = true;
          freezeAllRef.current();
        },
        onPerfTestComplete: (data) => {
          // All requested tokens were streamed for this session before the timeout.
          // Signal fanout completion (all tokens written to Redis streams).
          const _d = data as { total_tokens?: number; tps?: number };
          void _d; // unused but keep for future extension
          // Also signal fanout completion (all tokens written to Redis streams).
          if (!fanoutCompleteSignalledRef.current) {
            fanoutCompletedCountRef.current += 1;
            if (fanoutCompletedCountRef.current >= sessionsRef.current.length) {
              fanoutCompleteSignalledRef.current = true;
              setFanoutElapsedMs(Date.now() - fanoutStartMsRef.current);
            }
          }
          sessionClosed = true;
          closeSession(thread_id, "completed");
        },
        onDone: (data) => {
          sessionClosed = true;
          const { status } = data as { status: string };
          closeSession(
            thread_id,
            (["completed", "cancelled", "failed"].includes(status)
              ? status
              : "completed") as ThreadSession["status"]
          );
        },
        onFailed: (data) => {
          sessionClosed = true;
          const errMsg = (data as { message?: string; error?: string })?.message
            ?? (data as { message?: string; error?: string })?.error
            ?? "Stream failed";
          patch(thread_id, { error: errMsg });
          closeSession(thread_id, "failed");
        },
        onCancelled: () => {
          // Task-level cancel (e.g. node CancelledError on timeout) — keep the
          // EventSource open so the following perf_test_stopped / done events
          // can arrive.  Session closure is handled by onDone / onPerfTestStopped.
        },
        onClose: () => {
          if (!sessionClosed) {
            patch(thread_id, { status: "failed", error: "Connection closed unexpectedly", closed: true });
          }
        },
      });

      attachStream(thread_id, cleanup);
    },
    [patch, closeSession, attachStream]
  );

  // Ref guard: prevents React Strict Mode's double-effect from spawning a
  // second batch of 4 backend requests.  Refs survive the cleanup→remount
  // cycle that StrictMode performs in development.
  const didSpawnRef = useRef(false);

  useEffect(() => {
    if (didSpawnRef.current) {
      // StrictMode remount: backend requests were already fired; SSE connections
      // were closed by React's cleanup.  Reopen stream #1 (and reset its metrics)
      // without submitting a duplicate backend query.
      const now = Date.now();
      fanoutStartMsRef.current = now;
      fanoutCompleteSignalledRef.current = false;
      fanoutCompletedCountRef.current = 0;
      setFanoutElapsedMs(null);
      setSessions((prev) =>
        prev.map((s) =>
          s.thread_id === initialThreadId
            ? { ...s, status: "connecting" as const, tokens: 0, start_ms: now, last_token_ms: now, last_token_text: "", closed: false }
            : s
        )
      );
      openSessionStream(initialThreadId);
      return () => {
        cleanups.current.forEach((fn) => fn());
        timeouts.current.forEach(clearTimeout);
      };
    }
    didSpawnRef.current = true;

    const now = Date.now();
    fanoutStartMsRef.current = now;
    fanoutCompleteSignalledRef.current = false;
    fanoutCompletedCountRef.current = 0;
    setFanoutElapsedMs(null);
    setSessions([
      {
        thread_id: initialThreadId,
        label: `Stream #${labelCounter.current++}`,
        status: "connecting",
        tokens: 0,
        start_ms: now,
        last_token_ms: now,
        last_token_text: "",
        closed: false,
      },
    ]);
    openSessionStream(initialThreadId);

    // Spawn 4 additional concurrent streams immediately — all 5 hit the
    // backend simultaneously for maximum fanout throughput.
    const spawnExtra = async () => {
      await Promise.all(
        Array.from({ length: 4 }, async () => {
          try {
            const res = await submitQuery(
              "DO STREAMING PERFORMANCE TEST NOW",
              userToken,
              { perf_total_tokens: config.tokenCount, perf_timeout_secs: config.timeoutSecs, perf_num_requests: 5 },
            );
            const thread_id = res.thread_id;
            // Compute label outside the functional updater: React StrictMode
            // double-invokes updater functions which would increment the counter
            // twice and produce label gaps (Stream #1, #3, #5 …).
            const label = `Stream #${labelCounter.current++}`;
            setSessions((prev) => [
              ...prev,
              {
                thread_id,
                label,
                status: "connecting",
                tokens: 0,
                start_ms: Date.now(),
                last_token_ms: Date.now(),
                last_token_text: "",
                closed: false,
              },
            ]);
            openSessionStream(thread_id);
          } catch (err) {
            console.error("[perf_panel] initial spawn failed:", err);
          }
        })
      );
    };
    spawnExtra();

    return () => {
      cleanups.current.forEach((fn) => fn());
      timeouts.current.forEach(clearTimeout);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleComplete = useCallback(() => {
    freezeAll();
  }, [freezeAll]);

  const handleRestart = useCallback(async () => {
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
    const now = Date.now();
    fanoutStartMsRef.current = now;
    fanoutCompleteSignalledRef.current = false;
    fanoutCompletedCountRef.current = 0;
    setFanoutElapsedMs(null);
    setFrozen(false);
    prevTotalRef.current = 0;
    totalTokensRef.current = 0;
    setPerSecStats({ tps: 0, peak: 0 });
    setSessions([]);
    // Reset label counter so restarted streams are numbered from #1.
    labelCounter.current = 1;
    // 4. Spawn 5 fresh concurrent streams.
    await Promise.all(
      Array.from({ length: 5 }, async () => {
        try {
          const res = await submitQuery(
            "DO STREAMING PERFORMANCE TEST NOW",
            userToken,
            { perf_total_tokens: config.tokenCount, perf_timeout_secs: config.timeoutSecs, perf_num_requests: 5 },
          );
          const thread_id = res.thread_id;
          // Compute label outside the functional updater to avoid
          // StrictMode double-increment side-effects.
          const label = `Stream #${labelCounter.current++}`;
          setSessions((prev) => [
            ...prev,
            {
              thread_id,
              label,
              status: "connecting",
              tokens: 0,
              start_ms: Date.now(),
              last_token_ms: Date.now(),
              last_token_text: "",
              closed: false,
            },
          ]);
          openSessionStream(thread_id);
        } catch (err) {
          console.error("[perf_panel] restart spawn failed:", err);
        }
      })
    );
  }, [userToken, config, openSessionStream]);

  const handleAddRequest = useCallback(async (count: number = 1) => {
    await Promise.all(
      Array.from({ length: count }, async () => {
        try {
          const res = await submitQuery(
            "DO STREAMING PERFORMANCE TEST NOW",
            userToken,
            { perf_total_tokens: config.tokenCount, perf_timeout_secs: config.timeoutSecs, perf_num_requests: count },
          );
          const thread_id = res.thread_id;
          const label = `Stream #${labelCounter.current++}`;

          setSessions((prev) => [
            ...prev,
            {
              thread_id,
              label,
              status: "connecting",
              tokens: 0,
              start_ms: Date.now(),
              last_token_ms: Date.now(),
              last_token_text: "",
              closed: false,
            },
          ]);

          openSessionStream(thread_id);
        } catch (err) {
          console.error("[perf_panel] add request failed:", err);
        }
      }),
    );
  }, [userToken, config, openSessionStream]);

  const handleStopAll = useCallback(() => {
    sessions.forEach((s) => {
      if (!s.closed) {
        cancelQuery(s.thread_id).catch(() => {});
        closeSession(s.thread_id, "stopped");
      }
    });
  }, [sessions, closeSession]);

  const handleStopOne = useCallback(
    (thread_id: string) => {
      cancelQuery(thread_id).catch(() => {});
      closeSession(thread_id, "stopped");
    },
    [closeSession]
  );

  const totalTokens = useMemo(() => sessions.reduce((acc, s) => acc + s.tokens, 0), [sessions]);
  const activeCount = useMemo(() => sessions.filter((s) => !s.closed).length, [sessions]);
  const completedCount = useMemo(() => sessions.filter((s) => s.status === "completed").length, [sessions]);
  const avgTokenRate = useMemo(() => {
    const running = sessions.filter((s) => !s.closed && s.tokens > 0);
    if (!running.length) return 0;
    const rates = running.map((s) => {
      const elapsed = (Date.now() - s.start_ms) / 1000;
      return elapsed > 0 ? s.tokens / elapsed : 0;
    });
    return rates.reduce((a, b) => a + b, 0) / rates.length;
  }, [sessions]);

  useEffect(() => { totalTokensRef.current = totalTokens; }, [totalTokens]);

  // Keep sessionsRef current so onCompleted can read sessions.length without stale closures.
  useEffect(() => { sessionsRef.current = sessions; }, [sessions]);

  const [, setTick] = useState(0);
  useEffect(() => {
    if (!activeCount) return;
    const iv = setInterval(() => {
      setTick((t) => t + 1);
      const total = totalTokensRef.current;
      const tps = total - prevTotalRef.current;
      prevTotalRef.current = total;
      setPerSecStats((prev) => ({ tps, peak: Math.max(prev.peak, tps) }));
    }, 1000);
    return () => clearInterval(iv);
  }, [activeCount]);

  return {
    sessions,
    totalTokens,
    activeCount,
    completedCount,
    avgTokenRate,
    perSecStats,
    fanoutElapsedMs,
    frozen,
    handleAddRequest,
    handleRestart,
    handleComplete,
    handleStopAll,
    handleStopOne,
  };
}
