import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ackQuery, cancelQuery, submitPerfQuery, stablePerfStream } from "../../api";
import { resetShardClients } from "../../api/centrifugoClient";

const PERF_TRIGGER = "DO STREAMING PERFORMANCE TEST NOW";
import type { PendingTokenPatch, PerfTestConfig, ThreadSession } from "./types";

/** Build a perf trigger query string with params encoded as |{json} so the
 * backend stream_runner node can parse test_mode, total_tokens, etc. */
function buildPerfQuery(label: string, runId: string, cfg: PerfTestConfig): string {
  const params = JSON.stringify({
    test_mode: cfg.testMode,
    total_tokens: cfg.tokenCount,
    timeout_secs: cfg.timeoutSecs,
    token_per_sec: cfg.tokenPerSec,
  });
  return `${PERF_TRIGGER}|${params} - ${label} [${runId}]`;
}
import { TERMINAL_STATUSES } from "./types";
import { usePerfSession } from "../../services/streaming";
import { computeAggregateStats } from "./aggregateStats";
import type { AggregateStats } from "./aggregateStats";

/**
 * Returns true when the session has accumulated at least `max(3, ceil(timeoutSecs × 0.1))`
 * seconds of TPS history AND ≥ 70 % of those buckets each reach at least
 * 90 % of the target `tokenPerSec`.
 *
 * Rule:
 *   1. Require `minBuckets = max(3, ceil(timeoutSecs × 0.1))` history entries
 *      (minimum 3 s; e.g. 6 buckets for a 60-second timeout).
 *   2. Evaluate the most-recent `minBuckets` entries as the sliding window.
 *   3. Count buckets with TPS ≥ 0.9 × tokenPerSec (inclusive boundary).
 *   4. If that count / minBuckets ≥ 0.70 → stable.
 *
 * Exported so columns.tsx can use the same logic for the "(stable)" display hint.
 */
export function isSessionStable(
  tpsHistory: number[],
  tokenPerSec: number,
  timeoutSecs: number,
): boolean {
  if (tokenPerSec <= 0) return false;
  const minBuckets = Math.max(3, Math.ceil(timeoutSecs * 0.1));
  if (tpsHistory.length < minBuckets) return false;
  const window = tpsHistory.slice(-minBuckets);
  const threshold = 0.9 * tokenPerSec;
  const above = window.filter((v) => v >= threshold).length;
  return above / window.length >= 0.70;
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
  /** Pre-computed aggregate stats updated on the 1-second tick — passed directly
   *  to AggregateStatsHeader to prevent it from re-rendering every 100ms. */
  aggregateStats: AggregateStats;
  /**
   * Count of non-closed, non-terminal sessions that have reached the digesting
   * phase (digest_start_ms is set).  Updated reactively on every sessions render
   * so AggregateStatsHeader can show placeholder values before the first 1s tick.
   */
  activeDigestingCount: number;
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
  /**
   * Pending token patches accumulated by usePerfSession's onPerfTokenBatch.
   * Flushed into React state once per 100ms tick to cap render frequency.
   */
  const pendingTokenPatchesRef = useRef<Map<string, PendingTokenPatch>>(new Map());
  /** Ref mirror of config.tokenCount — used inside freezeAll without stale closure. */
  const tokenCountRef = useRef(config.tokenCount);
  /** Ref mirror of sessions state — readable inside the tick interval without stale closure. */
  const sessionsRef = useRef<ThreadSession[]>([]);
  /** Number of 100ms ticks elapsed (mod 10 drives the 1s sub-tick). */
  const centisTickRef = useRef(0);
  /** Per-session token snapshot at the last 1s tick — keyed by thread_id. */
  const prevSessionTokensRef = useRef<Map<string, number>>(new Map());
  /**
   * Wall-clock ms when each session's last 1s TPS bucket was recorded.
   * Used to normalize the first (and any sub-second) bucket by actual elapsed
   * time rather than assuming a full 1000 ms window.
   */
  const prevSessionTickMsRef = useRef<Map<string, number>>(new Map());
  const [frozen, setFrozen] = useState(false);

  /** Ref mirrors of config scalars — used inside setInterval/closeSession to avoid stale closures. */
  const tokenPerSecRef = useRef(config.tokenPerSec);
  const timeoutSecsRef = useRef(config.timeoutSecs);
  /** Tracks thread_ids for which a stable signal has already been sent to the backend. */
  const stableSignaledRef = useRef<Set<string>>(new Set());
  /**
   * Peak count of simultaneously stable concurrency-mode sessions seen across
   * all 1-second ticks.  Updated each tick; threaded into AggregateStats as
   * `maxStableCount` for the "Max Num Stable Streams" header metric.
   * Remains null for throughput-mode runs (no concurrency sessions), so the
   * header correctly shows "Max Num Digesting Streams" instead.
   */
  const maxStableCountRef = useRef<number | null>(null);
  /**
   * Peak count of simultaneously digesting sessions (any mode) seen across
   * all 1-second ticks.  Used as the "Max Num Stable Streams" value for
   * throughput-mode runs where stable count is not applicable.
   */
  const maxDigestingCountRef = useRef<number>(0);

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
    resetShardClients();
    timeouts.current.forEach(clearTimeout);
    timeouts.current.clear();
    // Discard all buffered token patches — no more updates after freeze.
    pendingTokenPatchesRef.current.clear();
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

  /**
   * Immediately flush the buffered token patch for a single session into React
   * state.  Called by usePerfSession's terminal path so the final token count
   * reaches the UI before closeSession sets closed=true.
   */
  const flushPendingForSession = useCallback((thread_id: string) => {
    const p = pendingTokenPatchesRef.current.get(thread_id);
    if (!p) return;
    pendingTokenPatchesRef.current.delete(thread_id);
    setSessions((prev) =>
      prev.map((s) => {
        if (s.thread_id !== thread_id) return s;
        if (s.closed || TERMINAL_STATUSES.has(s.status)) return s;
        return {
          ...s,
          tokens: p.forceTokensTotal !== undefined ? p.forceTokensTotal : s.tokens + p.tokensDelta,
          last_token_ms: p.last_token_ms,
          // Use first_token_ms as digest_start_ms for all test modes.
          // For throughput, pub_start_ms (ingest-complete time) arrives via Centrifugo
          // after all token batches, so it can be later than last_token_ms, making
          // elapsed = 0.  first_token_ms is always before last_token_ms and gives a
          // reliable Digest Time and 1-second TPS history anchor.
          digest_start_ms: s.digest_start_ms ?? p.first_token_ms,
          batch_first: s.batch_first ?? p.batch_first,
          batch_max: p.batch_max,
          batch_ave: p.batch_ave,
          batch_last: p.batch_last,
          stream_text: p.stream_text,
          status: p.status_transition ?? s.status,
        };
      })
    );
  }, []);

  const closeSession = useCallback(
    (thread_id: string, stream_id: string | null, finalStatus: ThreadSession["status"] = "cancelled") => {
      // Always clean up the EventSource and timeout, even if the session was
      // already marked closed (e.g. optimistic cancel patch).
      const cleanup = cleanups.current.get(thread_id);
      if (cleanup) { cleanup(); cleanups.current.delete(thread_id); }
      const tid = timeouts.current.get(thread_id);
      if (tid !== undefined) { clearTimeout(tid); timeouts.current.delete(thread_id); }

      // Drain any pending token patch so the final token count is accurate.
      // This handles late-connecting sessions where history-replay token batches
      // arrive after the group-stable tick has already set status="completed"
      // (which causes the normal 100ms tick flush to skip this session).
      const pendingPatch = pendingTokenPatchesRef.current.get(thread_id);
      if (pendingPatch) pendingTokenPatchesRef.current.delete(thread_id);

      // Only update status if the session was not already closed optimistically.
      // This prevents a backend `done` from overriding a user-initiated cancel
      // that was already reflected in the UI.
      setSessions((prev) =>
        prev.map((s) => {
          if (s.thread_id !== thread_id) return s;
          // When stream_id is known, skip sessions from a different stream run
          // to guard against stale events replayed on the same thread channel.
          if (stream_id && s.stream_id && s.stream_id !== stream_id) return s;
          // If already closed (optimistic cancel or tick auto-complete), preserve existing status.
          if (s.closed) return s;

          // Compute effective token count including any drained pending patch.
          const pendingDelta = pendingPatch
            ? (pendingPatch.forceTokensTotal !== undefined
                ? pendingPatch.forceTokensTotal - s.tokens
                : pendingPatch.tokensDelta)
            : 0;
          const effectiveTokens = s.tokens + Math.max(0, pendingDelta);

          // Definitive timeout→completed upgrade for concurrency mode.
          // Previous approach used isSessionStable() (tps_history-based), which fails for
          // late-connecting sessions that receive all tokens via history-replay in a burst
          // (the 1s TPS tick skips terminal-status sessions so tps_history stays empty).
          // New: upgrade if ANY tokens were received — in concurrency mode, timeout IS the
          // intended stop mechanism; a session that received tokens ran correctly.
          let resolvedStatus = finalStatus;
          if (finalStatus === "timeout" && s.test_mode === "concurrency") {
            if (effectiveTokens > 0) {
              resolvedStatus = "completed";
            }
          }

          console.info(
            "[perf] closeSession thread_id=%s finalStatus=%s resolved=%s tokens=%d pending=%d effective=%d",
            thread_id, finalStatus, resolvedStatus, s.tokens, pendingDelta, effectiveTokens,
          );
          return {
            ...s,
            tokens: effectiveTokens,
            digest_start_ms: s.digest_start_ms ?? pendingPatch?.first_token_ms,
            status: resolvedStatus,
            closed: true,
          };
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
    pendingTokenPatchesRef,
    flushPendingForSession,
  });

  /**
   * Unique run ID regenerated on every start/restart.
   * Appended to each query string so the partial unique index
   * uq_user_queries_dedup never matches rows from a previous run, which
   * prevents stale thread_ids from being returned as dedup_nack responses.
   */
  const runIdRef = useRef(crypto.randomUUID());

  // Ref guard: prevents React Strict Mode's double-effect from spawning a
  // second batch of 4 backend requests.  Refs survive the cleanup→remount
  // cycle that StrictMode performs in development.
  const didSpawnRef = useRef(false);

  /** Helper to build a fresh ThreadSession object. */
  const makeSession = useCallback(
    (thread_id: string, _label: string, test_mode: "throughput" | "concurrency", start_ms: number): ThreadSession => ({
      thread_id,
      node_id: null,
      leaf_node_id: null,
      task_id: null,
      stream_id: null,
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
              buildPerfQuery(label, runIdRef.current, config),
              userToken,
            );
            const thread_id = res.thread_id;
            submittedIdsRef.current.push(thread_id);
            // Set status='received' immediately from the HTTP response — don't wait for
            // Centrifugo history replay of query_status to avoid stale 'connecting' label.
            setSessions((prev) => prev.map((s) => s.thread_id === tempId ? { ...s, thread_id, status: "received" as const } : s));
            console.info("[perf] stream spawned thread_id=%s label=%s", thread_id, label);
            // ACK immediately — the HTTP response already confirms status='received' with
            // the backend-generated UUID. Don't wait for Centrifugo history replay of
            // query_received (subject to 600s TTL race).
            ackQuery(thread_id, userToken).catch((err) =>
              console.warn("[perf] immediate ack failed thread_id=%s", thread_id, err)
            );
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
    resetShardClients();
    timeouts.current.forEach(clearTimeout);
    timeouts.current.clear();
    // 3. Reset all tracking state.
    setFrozen(false);
    centisTickRef.current = 0;
    prevSessionTokensRef.current.clear();
    stableSignaledRef.current.clear();
    maxStableCountRef.current = null;
    maxDigestingCountRef.current = 0;
    pendingTokenPatchesRef.current.clear();
    totalTokensRef.current = 0;
    setSessions([]);
    // Reset counters for a clean restart and generate a new run ID to bypass
    // the dedup index for query strings from the previous run.
    labelCounter.current = 1;
    submittedIdsRef.current = [];
    runIdRef.current = crypto.randomUUID();
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
            buildPerfQuery(`Stream #${labelNum}`, runIdRef.current, config),
            userToken,
          );
          const thread_id = res.thread_id;
          submittedIdsRef.current.push(thread_id);
          // Set status='received' immediately — don't wait for Centrifugo event.
          setSessions((prev) => prev.map((s) => s.thread_id === tempId ? { ...s, thread_id, status: "received" as const } : s));
          console.info("[perf] restart stream spawned thread_id=%s label=%s", thread_id, label);
          ackQuery(thread_id, userToken).catch((err) =>
            console.warn("[perf] immediate ack (restart) failed thread_id=%s", thread_id, err)
          );
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
    const t0 = performance.now();
    console.info(
      "[perf-render] handleAddRequest count=%d pending_patches=%d sessions=%d",
      count, pendingTokenPatchesRef.current.size, sessionsRef.current.length,
    );
    await Promise.all(
      Array.from({ length: count }, async () => {
        const labelNum = labelCounter.current++;
        const label = `Stream #${labelNum}`;
        const spawnedAt = Date.now();
        const tempId = `pending-${labelNum}`;
        setSessions((prev) => [...prev, makeSession(tempId, label, config.testMode, spawnedAt)]);
        try {
          const res = await submitPerfQuery(
            buildPerfQuery(`Stream #${labelNum}`, runIdRef.current, config),
            userToken,
          );
          const thread_id = res.thread_id;
          // Set status='received' immediately — don't wait for Centrifugo event.
          setSessions((prev) => prev.map((s) => s.thread_id === tempId ? { ...s, thread_id, status: "received" as const } : s));
          console.info("[perf] add stream spawned thread_id=%s label=%s", thread_id, label);
          ackQuery(thread_id, userToken).catch((err) =>
            console.warn("[perf] immediate ack (add) failed thread_id=%s", thread_id, err)
          );
          openSessionStream(thread_id);
        } catch (err) {
          console.error("[perf_panel] add request failed:", err);
          setSessions((prev) => prev.map((s) => s.thread_id === tempId ? { ...s, status: "failed" as const, closed: true } : s));
        }
      }),
    );
    console.info("[perf-render] handleAddRequest done count=%d elapsed=%dms", count, Math.round(performance.now() - t0));
  }, [userToken, config, openSessionStream, makeSession]);

  const handleCancelAll = useCallback(() => {
    const active = sessions.filter((s) => !s.closed);
    console.info("[perf-render] cancel-all triggered active=%d pending_patches=%d", active.length, pendingTokenPatchesRef.current.size);
    active.forEach((s) => {
      // Optimistically show "cancelled" immediately; the EventSource stays open
      // until onCancelled (or onDone) fires from the backend and calls closeSession.
      patch(s.thread_id, { status: "cancelled", closed: true });
      if (!s.thread_id.startsWith("pending-")) {
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
      if (!thread_id.startsWith("pending-")) {
        cancelQuery(thread_id).catch(() => {});
      }
    },
    [patch],
  );

  const totalTokens = useMemo(() => sessions.reduce((acc, s) => acc + s.tokens, 0), [sessions]);
  const activeCount = useMemo(() => sessions.filter((s) => !s.closed && !TERMINAL_STATUSES.has(s.status)).length, [sessions]);
  const completedCount = useMemo(() => sessions.filter((s) => s.status === "completed").length, [sessions]);
  /** Sessions currently in the digest (streaming) phase — drives header visibility. */
  const activeDigestingCount = useMemo(
    () => sessions.filter((s) => !s.closed && !TERMINAL_STATUSES.has(s.status) && s.digest_start_ms != null).length,
    [sessions],
  );

  useEffect(() => { totalTokensRef.current = totalTokens; }, [totalTokens]);

  /**
   * Aggregate stats updated on the 1s sub-tick.  Passed directly to
   * AggregateStatsHeader so it does NOT re-render on every 100ms token flush.
   */
  const emptyStats: AggregateStats = {
    peakSumConcurrent: null, peakSingleStream: null,
    aveConcurrent: null, maxFirstTokenLatencyMs: null, sampleCount: 0,
    maxStableCount: null, maxDigestingCount: 0,
  };
  const [aggregateStats, setAggregateStats] = useState<AggregateStats>(emptyStats);
  /** Throttle diagnostic log: log flush metrics once every 50 ticks (~5s). */
  const flushLogTickRef = useRef(0);

  /**
   * Final stats computation when all sessions close.
   * Handles two cases:
   *   1. Tests that complete before the first 1s tick fires (duration < 1s).
   *   2. Normal test end — ensures frozen stats are correct after the interval clears.
   * Guard: only run when there are sessions with digest data to avoid clobbering
   * the emptyStats on initial mount.
   */
  useEffect(() => {
    if (activeCount > 0) return;
    if (sessionsRef.current.some((s) => (s.digest_start_ms != null || s.pub_start_ms != null) && s.tokens > 0)) {
      setAggregateStats(computeAggregateStats(sessionsRef.current, Date.now(), maxStableCountRef.current, maxDigestingCountRef.current));
    }
  }, [activeCount]);

  useEffect(() => {
    if (!activeCount) return;
    const iv = setInterval(() => {
      centisTickRef.current += 1;

      // ── 100ms: Flush pending token patches ───────────────────────────────────
      // Consolidate all buffered token-batch updates into a single setSessions call
      // to keep the React re-render rate ≤ 10/sec regardless of how many streams
      // are running.  Without this, onPerfTokenBatch would call setSessions on
      // every SSE event — hundreds of calls/sec with 100 concurrent streams.
      const pending = pendingTokenPatchesRef.current;
      if (pending.size > 0) {
        const snapshot = new Map(pending);
        pending.clear();
        // Diagnostic log every ~5 s to surface flush volume without flooding the console.
        flushLogTickRef.current += 1;
        if (flushLogTickRef.current % 50 === 1) {
          let totalDelta = 0;
          snapshot.forEach((p) => { totalDelta += p.tokensDelta; });
          void totalDelta;
        }
        setSessions((prev) =>
          prev.map((s) => {
            const p = snapshot.get(s.thread_id);
            if (!p) return s;
            if (s.closed || TERMINAL_STATUSES.has(s.status)) return s;
            return {
              ...s,
              tokens: p.forceTokensTotal !== undefined ? p.forceTokensTotal : s.tokens + p.tokensDelta,
              last_token_ms: p.last_token_ms,
              // Use first_token_ms as digest_start_ms for all test modes.
              // pub_start_ms (ingest-complete time) arrives after all token batches and
              // may be later than last_token_ms, making elapsed = 0.  first_token_ms
              // is always ≤ last_token_ms and gives a reliable Digest Time anchor.
              digest_start_ms: s.digest_start_ms ?? p.first_token_ms,
              batch_first: s.batch_first ?? p.batch_first,
              batch_max: p.batch_max,
              batch_ave: p.batch_ave,
              batch_last: p.batch_last,
              stream_text: p.stream_text,
              status: p.status_transition ?? s.status,
            };
          })
        );
      }

      // ── 1 s sub-tick (every 10th 100 ms tick) ────────────────────────────────
      // TPS is measured over a 1-second window to avoid JS event-loop timer
      // jitter that inflates short windows: a late 100ms tick could appear to
      // carry 300ms worth of tokens, tripling the apparent rate.
      if (centisTickRef.current % 10 === 0) {
        // ── Concurrency stable signal ────────────────────────────────────────
        // Read sessions via ref (avoids stale closure) and send the backend
        // stable signal BEFORE setSessions so it is dispatched even when the
        // state update marks sessions as completed in this same tick.
        //
        // Guard: ALL active concurrency sessions must have reached digesting
        // (digest_start_ms set) before evaluating stability.  Sessions still in
        // connecting/received/preparing/ingesting are not yet streaming — firing
        // the stable signal while any session hasn't started would end the test
        // prematurely for the ones that are already streaming.
        // Append per-second TPS bucket and evaluate auto-terminal conditions.
        // NOTE: stable/digesting peak counts are updated INSIDE setSessions below
        // (using withHistory which includes the current tick's bucket) to avoid a
        // 1-tick lag — otherwise sessions are marked "completed" (TERMINAL_STATUS)
        // in the same setSessions call where stability is first detected.
        //
        // The backend stable signal is dispatched INSIDE setSessions (via
        // Promise.resolve) at the exact tick where concurrencyGroupStable first
        // becomes true.  The previous approach dispatched the signal from a
        // pre-setSessions check using sessionsRef.current (1-tick stale), which
        // caused the signal to be missed: once sessions are marked "completed"
        // (TERMINAL_STATUS), the outer filter excludes them from the next tick's
        // allConcurrentNow check, so the signal was never sent.
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
        // Capture wall-clock time once so all buckets in this tick share
        // the same reference point regardless of JS event-loop jitter.
        const tickNow = Date.now();
        setSessions((prev) => {
          // ── Pass 1: accumulate TPS histories ──────────────────────────────────
          const withHistory = prev.map((s) => {
            if (s.closed || TERMINAL_STATUSES.has(s.status)) {
              prevSessionTokensRef.current.delete(s.thread_id);
              prevSessionTickMsRef.current.delete(s.thread_id);
              return s;
            }
            if (s.digest_start_ms == null) {
              // Streaming not started yet; keep snapshot untouched.
              return s;
            }
            const prevTok = prevSessionTokensRef.current.get(s.thread_id) ?? 0;
            const delta = Math.max(0, s.tokens - prevTok);
            prevSessionTokensRef.current.set(s.thread_id, s.tokens);
            // Normalize by actual elapsed time so the first (sub-second) bucket
            // is not under-reported when digest_start_ms falls mid-window.
            const lastTickMs = prevSessionTickMsRef.current.get(s.thread_id);
            const refMs = lastTickMs ?? s.digest_start_ms;
            const elapsedMs = Math.max(50, tickNow - refMs);
            const tps = Math.round(delta / (elapsedMs / 1000));
            prevSessionTickMsRef.current.set(s.thread_id, tickNow);
            return { ...s, tps_history: [...(s.tps_history ?? []), tps] };
          });

          // ── Pass 2: group stability check for concurrency ─────────────────────
          // "completed" fires only when EVERY *participating* concurrency session is
          // individually stable.  Sessions that have not yet reached the digesting
          // phase (digest_start_ms == null) are counted against the requirement ONLY
          // while they are within the startup grace period.  After the grace period
          // (8 s from start_ms), sessions that still have not started streaming are
          // treated as "failed to start" and excluded from the group requirement so
          // the remaining healthy sessions can still trigger group stability.
          const STARTUP_GRACE_MS = 8_000;
          const allConcurrent = withHistory.filter(
            (s) => !s.closed && !TERMINAL_STATUSES.has(s.status) &&
                   s.test_mode === "concurrency",
          );
          // Partition: sessions still within startup window vs stuck/failed-to-start.
          const participatingConcurrent = allConcurrent.filter(
            (s) => s.digest_start_ms != null ||
                   (tickNow - s.start_ms) < STARTUP_GRACE_MS,
          );
          const concurrencyGroupStable =
            participatingConcurrent.length > 0 &&
            participatingConcurrent.every((s) =>
              s.digest_start_ms != null &&
              isSessionStable(s.tps_history ?? [], tokenPerSecRef.current, timeoutSecsRef.current),
            );
          // activeConcurrent used only for peak-count metrics below.
          const activeConcurrent = allConcurrent.filter(
            (s) => s.digest_start_ms != null,
          );

          // Update peak stable count using withHistory (current tick's bucket
          // is already appended), BEFORE terminal pass marks sessions completed.
          if (activeConcurrent.length > 0) {
            const stableCountNow = activeConcurrent.filter((s) =>
              isSessionStable(s.tps_history ?? [], tokenPerSecRef.current, timeoutSecsRef.current),
            ).length;
            if (stableCountNow > (maxStableCountRef.current ?? -1)) {
              maxStableCountRef.current = stableCountNow;
            }
          }

          // Update peak digesting count using withHistory.
          const digestingCountNow = withHistory.filter(
            (s) => !s.closed && !TERMINAL_STATUSES.has(s.status) && s.digest_start_ms != null,
          ).length;
          if (digestingCountNow > maxDigestingCountRef.current) {
            maxDigestingCountRef.current = digestingCountNow;
          }

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
            // The backend stable signal is dispatched here (via Promise.resolve so it is
            // scheduled outside the state updater) at the exact tick where stability is
            // first detected.  stableSignaledRef guards against double-dispatch in
            // React StrictMode (which calls state updaters twice in development).
            if (s.test_mode === "concurrency" && concurrencyGroupStable) {
              if (!stableSignaledRef.current.has(s.thread_id)) {
                stableSignaledRef.current.add(s.thread_id);
                const tidForSignal = s.thread_id;
                const sidForSignal = s.stream_id;
                Promise.resolve().then(() => {
                  if (!sidForSignal) {
                    console.warn("[perf] stable signal skipped — stream_id not yet known thread_id=%s", tidForSignal);
                    return;
                  }
                  console.info("[perf] stable → backend thread_id=%s stream_id=%s", tidForSignal, sidForSignal);
                  stablePerfStream(tidForSignal, sidForSignal, userToken)
                    .then(() => console.info("[perf] stable signal sent thread_id=%s stream_id=%s", tidForSignal, sidForSignal))
                    .catch((e) => console.warn("[perf] stable signal failed", tidForSignal, sidForSignal, e));
                });
              }
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

        // Update aggregate stats on the 1s tick so AggregateStatsHeader only
        // re-renders once per second instead of on every 100ms token flush.
        setAggregateStats(computeAggregateStats(sessionsRef.current, tickNow, maxStableCountRef.current, maxDigestingCountRef.current));
      }

      // NOTE: setTick removed — the pending-patch flush's setSessions call
      // above already drives 100ms re-renders when tokens are flowing.
      // This reduces one full re-render cycle per tick when no patches exist.
    }, 100);
    return () => clearInterval(iv);
  }, [activeCount]);

  return {
    sessions,
    totalTokens,
    activeCount,
    completedCount,
    aggregateStats,
    activeDigestingCount,
    frozen,
    handleAddRequest,
    handleRestart,
    handleComplete,
    handleCancelAll,
    handleCancelOne,
  };
}
