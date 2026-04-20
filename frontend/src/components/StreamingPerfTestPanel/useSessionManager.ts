import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { cancelQuery, submitQuery } from "../../api";
import type { PerfTestConfig, ThreadSession } from "./types";
import { useBrowserStreamSession } from "./useBrowserStreamSession";
import { useLocustStreamSession } from "./useLocustStreamSession";

interface UseSessionManagerReturn {
  sessions: ThreadSession[];
  totalTokens: number;
  activeCount: number;
  completedCount: number;
  avgTokenRate: number;
  perSecStats: { tps: number; peak: number };
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
  const [frozen, setFrozen] = useState(false);

  // Ref so openSessionStream can call freezeAll without becoming stale —
  // avoids re-creating stream closures whenever sessions changes.
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
    [],
  );

  const closeSession = useCallback(
    (thread_id: string, finalStatus: ThreadSession["status"] = "stopped") => {
      const cleanup = cleanups.current.get(thread_id);
      if (cleanup) { cleanup(); cleanups.current.delete(thread_id); }
      const tid = timeouts.current.get(thread_id);
      if (tid !== undefined) { clearTimeout(tid); timeouts.current.delete(thread_id); }
      patch(thread_id, { status: finalStatus, closed: true });
    },
    [patch],
  );

  const browserSession = useBrowserStreamSession({
    cleanups,
    timeouts,
    config,
    patch,
    setSessions,
    closeSession,
    freezeAllRef,
    totalTokensRef,
  });
  const locustSession = useLocustStreamSession({
    cleanups,
    timeouts,
    config,
    patch,
    setSessions,
    closeSession,
    freezeAllRef,
    totalTokensRef,
  });
  const { openSessionStream } = config.pubMode === "locust" ? locustSession : browserSession;

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
        pub_mode: config.pubMode,
      },
    ]);
    openSessionStream(initialThreadId);

    // Spawn (config.initialRequestCount - 1) additional concurrent streams so that
    // the total concurrent streams equals config.initialRequestCount.
    const spawnExtra = async () => {
      await Promise.all(
        Array.from({ length: config.initialRequestCount - 1 }, async () => {
          try {
            const res = await submitQuery(
              "DO STREAMING PERFORMANCE TEST NOW",
              userToken,
              { perf_total_tokens: config.tokenCount, perf_timeout_secs: config.timeoutSecs, perf_pub_mode: config.pubMode },
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
                pub_mode: config.pubMode,
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
    setFrozen(false);
    prevTotalRef.current = 0;
    totalTokensRef.current = 0;
    setPerSecStats({ tps: 0, peak: 0 });
    setSessions([]);
    // Reset label counter so restarted streams are numbered from #1.
    labelCounter.current = 1;
    // 4. Spawn config.initialRequestCount fresh concurrent streams.
    await Promise.all(
      Array.from({ length: config.initialRequestCount }, async () => {
        try {
          const res = await submitQuery(
            "DO STREAMING PERFORMANCE TEST NOW",
            userToken,
            { perf_total_tokens: config.tokenCount, perf_timeout_secs: config.timeoutSecs, perf_pub_mode: config.pubMode },
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
              pub_mode: config.pubMode,
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
            { perf_total_tokens: config.tokenCount, perf_timeout_secs: config.timeoutSecs, perf_pub_mode: config.pubMode },
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
              pub_mode: config.pubMode,
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
    [closeSession],
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
    frozen,
    handleAddRequest,
    handleRestart,
    handleComplete,
    handleStopAll,
    handleStopOne,
  };
}
