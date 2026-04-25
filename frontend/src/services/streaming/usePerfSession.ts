import { useCallback } from "react";
import type React from "react";
import { cancelQuery, createAckHandlers, fetchStreamingStatus, openStream } from "../../api";
import { DoneConditionGuard, sendDoneAck } from "./lifecycle";
import type { PerfTestConfig, ThreadSession } from "../../components/StreamingPerfTestPanel/types";
import { TERMINAL_STATUSES } from "../../components/StreamingPerfTestPanel/types";

export interface PerfSessionDeps {
  cleanups: React.MutableRefObject<Map<string, () => void>>;
  timeouts: React.MutableRefObject<Map<string, ReturnType<typeof setTimeout>>>;
  config: PerfTestConfig;
  patch: (thread_id: string, delta: Partial<ThreadSession>) => void;
  setSessions: React.Dispatch<React.SetStateAction<ThreadSession[]>>;
  closeSession: (thread_id: string, finalStatus?: ThreadSession["status"]) => void;
  freezeAllRef: React.MutableRefObject<() => void>;
  totalTokensRef: React.MutableRefObject<number>;
  /** Guest user token required to send the query ACK. */
  userToken: string;
}

export interface UsePerfSessionReturn {
  /** Open the SSE stream for a single session. */
  openSessionStream: (thread_id: string) => void;
}

/**
 * Unified SSE stream lifecycle hook for perf-test sessions.
 *
 * Manages the browser pub mode: per-token events (`perf_token_batch`),
 * two-phase ingest/pub lifecycle, ACK handshake, phase transitions,
 * and safety timeout.
 *
 * Explicit dequeue: every terminal event handler (`done`, `failed`,
 * `perf_test_stopped`, `perf_test_complete`) calls `dequeue()` — which closes
 * the EventSource immediately via the local cleanup ref — before delegating
 * state updates to `closeSession`.  This releases the HTTP/2 stream slot at
 * the earliest possible moment and removes the session from the shared cleanup
 * registry so that `freezeAll` and a later `closeSession` call are both
 * idempotent and do not double-invoke `es.close()`.
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
  } = deps;

  const openSessionStream = useCallback(
    (thread_id: string) => {
      let sessionClosed = false;
      let lastIngestLogPct = -1;
      let lastTokenLogPct = -1;
      // Running total of tokens received for this session — incremented
      // synchronously in onPerfTokenBatch so we can compare against the
      // target without relying on the async setSessions state.
      let tokensReceived = 0;
      // Backend-authoritative token count — updated from perf_test_complete,
      // perf_test_stopped, and completed(mock_pub) events.  May be less than
      // config.tokenCount when the backend's ingest phase timed out early.
      // Used as the completion target instead of config.tokenCount so the
      // pendingComplete guard resolves correctly even for short runs.
      let actualTokensExpected = config.tokenCount;
      // Two-channel race guard: perf_test_complete / done travel via Redis Pub/Sub
      // (fast) while perf_token_batch travels via Redis Streams (slower XREAD).
      // If a completion event arrives before all tokens are counted, set this
      // flag and let onPerfTokenBatch call terminate once the count is satisfied.
      // pendingTerminalStatus holds the status to use when the guard resolves.
      let pendingComplete = false;
      let pendingTerminalStatus: ThreadSession["status"] = "completed";
      // DoneConditionGuard replaces the raw drain-window setTimeout.
      // Created in onDone when pendingComplete is set; recheck() is called from
      // onPerfTokenBatch when additional token batches arrive.  The guard's own
      // 3-second window fires terminate(pendingTerminalStatus) as a safety net
      // when tokens never reach the expected count.
      let doneGuard: DoneConditionGuard | null = null;
      // Batch-size statistics tracked synchronously in the closure.
      let batchFirst: number | undefined;
      let batchMax = 0;
      let batchSum = 0;
      let batchCount = 0;

      /**
       * Probe the backend streaming-health endpoint and log diagnostic info.
       * Called whenever a session closes before receiving all expected tokens.
       */
      const probeBackend = (reason: string) => {
        fetchStreamingStatus(thread_id).then((s) => {
          console.warn(
            "[perf] backend-probe reason=%s thread_id=%s query_status=%s is_active=%s " +
            "last_token_ms_ago=%s running_tasks=%d tokens_received=%d tokens_expected=%d",
            reason, thread_id, s.query_status, s.is_active,
            s.last_token_ms_ago == null ? "n/a" : `${s.last_token_ms_ago}ms`,
            s.running_tasks.length,
            tokensReceived, config.tokenCount,
          );
          if (s.running_tasks.length > 0) {
            console.warn(
              "[perf] backend-probe still-running tasks: %s",
              s.running_tasks.map((t) => t.task_key).join(", "),
            );
          }
        }).catch((e) => {
          console.warn("[perf] backend-probe failed reason=%s thread_id=%s err=%s", reason, thread_id, e);
        });
      };

      /**
       * Explicit dequeue: close the EventSource immediately and remove this
       * session from the shared cleanup registry and timeout map.
       * Called by every terminal event handler so:
       *  - the HTTP/2 stream slot is released without waiting for GC;
       *  - `freezeAll` and any following `closeSession` are no-ops for this session.
       */
      let esCleanup: (() => void) | null = null;
      const dequeue = () => {
        esCleanup?.();
        esCleanup = null;
        cleanups.current.delete(thread_id);
        const tid = timeouts.current.get(thread_id);
        if (tid !== undefined) {
          clearTimeout(tid);
          timeouts.current.delete(thread_id);
        }
      };

      /**
       * Idempotent terminal close: noop if already closed.
       * Sets sessionClosed, sends done-ACK if `done` was received, dequeues
       * the EventSource/timeout, and delegates final status to closeSession.
       *
       * @param finalStatus - terminal status to report to the session store.
       * @param ackDone     - true when terminating from a `done`-signal path;
       *                      sends the done-ACK to the backend before closing.
       */
      const terminate = (finalStatus: ThreadSession["status"], ackDone = false) => {
        if (sessionClosed) return;
        sessionClosed = true;
        doneGuard?.cleanup();
        doneGuard = null;
        dequeue();
        if (ackDone) {
          sendDoneAck(thread_id, userToken, finalStatus).catch((err) => {
            console.warn("[perf] done-ack failed thread_id=%s", thread_id, err);
          });
        }
        closeSession(thread_id, finalStatus);
      };

      /**
       * Create and trigger a DoneConditionGuard for the drain-window phase.
       * Idempotent — if a guard already exists this is a no-op.
       * The guard's onReady sends the done-ACK and terminates the session.
       *
       * @param targetStatus - status to use when the guard resolves.
       */
      const activateDrainGuard = (targetStatus: ThreadSession["status"]) => {
        if (doneGuard) return; // already active
        doneGuard = new DoneConditionGuard({
          label: `perf:${thread_id}`,
          drainWindowMs: 3_000,
          conditions: [() => tokensReceived >= actualTokensExpected],
          onReady: (forced) => {
            console.info(
              "[perf] drain-guard resolved forced=%s status=%s gap=%d thread_id=%s",
              forced, targetStatus, actualTokensExpected - tokensReceived, thread_id,
            );
            terminate(targetStatus, /* ackDone */ true);
          },
        });
        doneGuard.trigger();
      };

      console.info("[perf] opening stream thread_id=%s", thread_id);

      const cleanup = openStream(thread_id, {
        // ── ACK handshake ────────────────────────────────────────────────────
        ...createAckHandlers(thread_id, userToken, "perf"),

        // ── Phase-transition status ──────────────────────────────────────────
        onQueryStatus: (data) => {
          const d = data as { phase?: string };
          const phaseToStatus: Record<string, ThreadSession["status"]> = {
            received:  "received",
            preparing: "preparing",
            ingesting: "ingesting",
            digesting: "digesting",
          };
          const newStatus = phaseToStatus[d.phase ?? ""];
          if (newStatus) {
            console.info("[perf] %s → %s", thread_id, newStatus);
            // Guard: do not override a terminal status on an already-closed session.
            setSessions((prev) =>
              prev.map((s) => {
                if (s.thread_id !== thread_id || s.closed) return s;
                return { ...s, status: newStatus };
              })
            );
          }
        },

        // ── Shared ingest-phase events ────────────────────────────────────────
        onPerfIngestProgress: (data) => {
          const d = data as { produced?: number; total_tokens?: number; ingest_tps?: number; status?: string };
          if (d.total_tokens) {
            const pct = Math.floor((d.produced ?? 0) / d.total_tokens * 100);
            const milestone = pct - (pct % 25);
            if (milestone > lastIngestLogPct) {
              lastIngestLogPct = milestone;
              console.info(
                "[perf] ingest %s %d%% (%d/%d) tps=%d",
                thread_id, milestone, d.produced ?? 0, d.total_tokens,
                Math.round(d.ingest_tps ?? 0),
              );
            }
          }
          const isIngestDone = d.status === "completed" || d.status === "timeout";
          setSessions((prev) =>
            prev.map((s) => {
              if (s.thread_id !== thread_id) return s;
              // Guard: once the session has reached a terminal status (e.g. "completed"
              // from the group-stability tick) or is closed, stop applying ingest-progress
              // updates so the ingest counter does not keep climbing after the lifecycle ends.
              if (s.closed || TERMINAL_STATUSES.has(s.status)) return s;
              return {
                ...s,
                ingest_produced: d.produced,
                ingest_total: d.total_tokens,
                ingest_tps: d.ingest_tps,
                ingest_status: (d.status === "running" || d.status === "completed" || d.status === "timeout")
                  ? d.status
                  : "running",
                pub_start_ms: s.pub_start_ms ?? (isIngestDone ? Date.now() : undefined),
              };
            })
          );
        },

        onPerfIngestComplete: (data) => {
          const d = data as { produced?: number; stop_reason?: string };
          const status = d.stop_reason === "timeout" ? "timeout" as const : "completed" as const;
          console.info(
            "[perf] ingest complete %s produced=%d stop_reason=%s",
            thread_id, d.produced ?? 0, d.stop_reason ?? "ok",
          );
          patch(thread_id, {
            ingest_produced: d.produced,
            ingest_status: status,
            pub_start_ms: Date.now(),
          });
        },

        // ── Task lifecycle ─────────────────────────────────────────────────────
        onStarted: () => {
          // No-op: perf_token_batch events are always forwarded regardless of
          // watch state, so token counting works without watch-registry wiring.
        },

        onCompleted: (data) => {
          const d = data as { task_key?: string; output?: Record<string, unknown> };
          const key = d?.task_key ?? "";
          console.info("[perf] task completed %s key=%s", thread_id, key);

          if (key === "perf_test_streamer.mock_ingest") {
            // Phase-1 ingest task completed; second half still running concurrently.
            // onPerfIngestHalfComplete handles the visual state; set pub_start_ms as fallback.
            patch(thread_id, { pub_start_ms: Date.now() });
            return;
          }

          if (key === "perf_test_streamer.mock_pub") {
            // Capture the authoritative published count from the backend task output.
            // This is the ground truth for how many tokens the SSE stream will carry.
            const backendPublished = d?.output?.["total_published"];
            if (typeof backendPublished === "number" && backendPublished > 0) {
              actualTokensExpected = backendPublished;
              console.info(
                "[perf] mock_pub completed total_published=%d (was config.tokenCount=%d) thread_id=%s",
                backendPublished, config.tokenCount, thread_id,
              );
            }
            patch(thread_id, { pub_status: "completed" });
            return;
          }
        },

        // ── Browser-only events ────────────────────────────────────────────────
        onPerfTokenBatch: (data) => {
          // Guard: ignore token events that arrive after any terminal lifecycle
          // event has fired.  This covers two cases:
          //   1. Buffered SSE events delivered from the EventSource queue after
          //      es.close() was already called (perf_test_stopped / done path).
          //   2. Tokens arriving while the EventSource is still open after an
          //      optimistic cancel (handleCancelOne sets s.closed=true in React
          //      state but cannot set sessionClosed in this closure).
          // Case 2 is handled by the s.closed guard inside setSessions below.
          if (sessionClosed) return;
          const d = data as { count?: number; recent_tokens?: string[] };
          const count = d.count ?? 1;
          tokensReceived += count;
          // Update batch stats synchronously in the closure.
          if (batchFirst === undefined) batchFirst = count;
          if (count > batchMax) batchMax = count;
          batchSum += count;
          batchCount += 1;
          const batchAve = Math.round(batchSum / batchCount);
          const now = Date.now();
          // recent_tokens from the backend is already a rolling window of last 10.
          // Build stream_text: "…\n" history indicator + tokens one per line.
          const recentTokens = d.recent_tokens ?? [];
          const stream_text = (tokensReceived > recentTokens.length ? "…\n" : "") + recentTokens.join("\n");
          setSessions((prev) =>
            prev.map((s) => {
              if (s.thread_id !== thread_id) return s;
              if (s.closed) return s;
              // Guard: once the tick has marked the session as a terminal status
              // (e.g. "completed" for concurrency stable), stop updating metrics
              // so Digest Time, Token Rate and Progress stay frozen.
              if (TERMINAL_STATUSES.has(s.status)) return s;
              const activeStatus =
                s.status === "connecting" || s.status === "received" ||
                s.status === "preparing" || s.status === "ingesting"
                  ? "digesting" as const
                  : s.status;
              // When this batch exactly fills the expected token budget, write the
              // authoritative tokensReceived into s.tokens rather than s.tokens+count.
              // s.tokens is React state that may lag behind the closure variable by
              // several batches (React defers / batches setSessions calls).  Using
              // tokensReceived ensures the displayed count freezes at the correct
              // value when closeSession sets s.closed=true in the same flush.
              const isLastBatch = tokensReceived >= actualTokensExpected && config.testMode === "throughput";
              return {
                ...s,
                status: activeStatus,
                tokens: isLastBatch ? tokensReceived : s.tokens + count,
                last_token_ms: now,
                digest_start_ms: s.digest_start_ms ?? now,
                batch_first: batchFirst,
                batch_max: batchMax,
                batch_ave: batchAve,
                batch_last: count,
                stream_text,
              };
            })
          );
          // Auto-complete in throughput mode: all tokens received — close session immediately.
          // Concurrency mode sessions end via perf_test_stopped (timeout) instead.
          if (tokensReceived >= actualTokensExpected && config.testMode === "throughput") {
            const status = pendingComplete ? pendingTerminalStatus : "completed";
            console.info(
              "[perf] all tokens received %s tokensReceived=%d actualExpected=%d reactTokensLag=%s status=%s",
              thread_id, tokensReceived, actualTokensExpected,
              pendingComplete ? "(pendingComplete)" : "(normal)", status,
            );
            if (pendingComplete && doneGuard) {
              // Guard is active — let it handle sendDoneAck + terminate
              // via its onReady callback once recheck() confirms the condition.
              doneGuard.recheck();
            } else {
              // Guard not yet created (onDone hasn't arrived) or normal path
              // (no pendingComplete) — terminate directly.
              terminate(status, /* ackDone */ pendingComplete);
            }
          } else if (config.testMode === "throughput") {
            // Log progress every 10 % milestone.
            const pct = Math.floor((tokensReceived / actualTokensExpected) * 100);
            const milestone = pct - (pct % 10);
            if (milestone > lastTokenLogPct) {
              lastTokenLogPct = milestone;
              console.info(
                "[perf] token-rx %s %d%% (%d/%d) pending_complete=%s",
                thread_id, milestone, tokensReceived, actualTokensExpected, pendingComplete,
              );
            }
            // When pendingComplete is set but tokens keep arriving, probe backend at 95 %.
            if (pendingComplete && pct >= 95 && lastTokenLogPct < 95) {
              lastTokenLogPct = 95;
              console.warn(
                "[perf] pending-complete stall: received=%d expected=%d gap=%d thread_id=%s",
                tokensReceived, actualTokensExpected, actualTokensExpected - tokensReceived, thread_id,
              );
              probeBackend("pending_complete_95pct");
            }
          }
        },

        onPerfConcurrentStatus: (data) => {
          // Adaptive reader metrics emitted every 1 s during concurrent Phase-2.
          // Guard: do not update once the session has reached a terminal status
          // (e.g. "completed" from the stability tick) — backend is still draining
          // its sentinel but the UI must stay frozen.
          const d = data as {
            batch_size?: number;
            digest_tps?: number;
            ingest_tps?: number;
            stream_len?: number;
          };
          setSessions((prev) =>
            prev.map((s) => {
              if (s.thread_id !== thread_id) return s;
              if (s.closed || TERMINAL_STATUSES.has(s.status)) return s;
              return {
                ...s,
                concurrent_batch_size: d.batch_size,
                concurrent_digest_tps: d.digest_tps,
                concurrent_ingest_tps: d.ingest_tps,
                concurrent_stream_len: d.stream_len,
              };
            }),
          );
        },

        // ── Terminal lifecycle events ──────────────────────────────────────────
        // All handlers delegate to terminate(), which is idempotent — whichever
        // event fires first wins; later events (including onDone as a fallback)
        // are no-ops.
        onPerfTestStopped: (data) => {
          const d = data as { duration_secs?: number; total_published?: number };
          // Use the backend's authoritative published count if provided — it may
          // be less than config.tokenCount when ingest hit the deadline early.
          if (d.total_published != null && d.total_published > 0) {
            actualTokensExpected = d.total_published;
          }
          console.info(
            "[perf] perf_test_stopped %s total_published=%d tokens_received=%d actualExpected=%d",
            thread_id, d.total_published ?? 0, tokensReceived, actualTokensExpected,
          );
          if (config.testMode === "throughput" && tokensReceived < actualTokensExpected) {
            // Backend stopped before client received all published tokens — defer
            // terminate until onPerfTokenBatch delivers the remaining ones.
            pendingComplete = true;
            pendingTerminalStatus = "timeout";
            console.warn(
              "[perf] perf_test_stopped deferred: received=%d expected=%d gap=%d thread_id=%s",
              tokensReceived, actualTokensExpected, actualTokensExpected - tokensReceived, thread_id,
            );
            probeBackend("perf_test_stopped_deferred");
            return;
          }
          // For concurrency mode the backend always emits perf_test_stopped before
          // done, so onDone will be a no-op (sessionClosed=true).  Send done-ACK
          // here so the backend's pending-notify entry is cleared immediately.
          const concurrencyStopped = config.testMode === "concurrency";
          terminate("timeout", /* ackDone */ concurrencyStopped);
        },

        onPerfTestComplete: (data) => {
          const d = data as { total_tokens?: number; tps?: number };
          // Update actualTokensExpected from the event payload — ground truth from backend.
          if (d.total_tokens != null && d.total_tokens > 0) {
            actualTokensExpected = d.total_tokens;
          }
          console.info(
            "[perf] perf test complete %s tokens_received=%d actualExpected=%d",
            thread_id, tokensReceived, actualTokensExpected,
          );
          // Guard against the two-channel race: Redis Pub/Sub arrives before the last
          // Redis Stream token batches.  Defer terminate until onPerfTokenBatch
          // confirms all tokens are counted.
          if (config.testMode === "throughput" && tokensReceived < actualTokensExpected) {
            pendingComplete = true;
            pendingTerminalStatus = "completed";
            console.info(
              "[perf] perf_test_complete early arrival — awaiting %d tokens thread_id=%s",
              actualTokensExpected - tokensReceived, thread_id,
            );
            probeBackend("perf_test_complete_early");
            return;
          }
          // For concurrency mode the backend always emits perf_test_complete before
          // done, so onDone will be a no-op (sessionClosed=true).  Send done-ACK
          // here so the backend's pending-notify entry is cleared immediately.
          const concurrencyComplete = config.testMode === "concurrency";
          terminate("completed", /* ackDone */ concurrencyComplete);
        },

        onDone: (data) => {
          const { status } = data as { status: string };
          console.info("[perf] done %s status=%s tokens_received=%d actualExpected=%d", thread_id, status, tokensReceived, actualTokensExpected);
          // Guard: ignore if already closed (e.g. user cancel, or auto-complete fired first).
          if (sessionClosed) return;
          const finalStatus = TERMINAL_STATUSES.has(status as ThreadSession["status"])
            ? (status as ThreadSession["status"])
            : "completed";
          // When pendingComplete is set and `done` arrives, the backend SSE gateway
          // may still forward trailing perf_token_batch events via its post-drain
          // window (up to 100 ms).  Keep the EventSource open so those batches reach
          // onPerfTokenBatch and auto-complete at 100 %.  A 3-second drain-window
          // timer acts as a safety net: if tokens don't reach 100 % in time, close
          // with pendingTerminalStatus.  Only one timer is started per session to
          // prevent accumulation on EventSource reconnects.
          if (pendingComplete) {
            // pendingComplete was set by onPerfTestComplete / onPerfTestStopped:
            // tokens haven't all arrived yet.  Activate the drain guard so the
            // EventSource stays open until onPerfTokenBatch satisfies the count
            // condition, or the 3-second window expires.
            console.warn(
              "[perf] done with pendingComplete — gap=%d, activating drain guard thread_id=%s",
              actualTokensExpected - tokensReceived, thread_id,
            );
            probeBackend("done_with_pending_complete");
            activateDrainGuard(pendingTerminalStatus);
            return;
          }
          if (finalStatus === "completed" && config.testMode === "throughput" && tokensReceived < actualTokensExpected) {
            // `done` arrived before perf_test_complete with all tokens still in flight.
            pendingComplete = true;
            pendingTerminalStatus = "completed";
            console.info(
              "[perf] done early arrival — activating drain guard gap=%d thread_id=%s",
              actualTokensExpected - tokensReceived, thread_id,
            );
            probeBackend("done_early");
            activateDrainGuard("completed");
            return;
          }
          if (finalStatus !== "completed" && config.testMode === "throughput" && tokensReceived < actualTokensExpected) {
            console.warn(
              "[perf] short close on done: status=%s received=%d expected=%d gap=%d",
              finalStatus, tokensReceived, actualTokensExpected, actualTokensExpected - tokensReceived,
            );
            probeBackend(`done_${finalStatus}`);
          }
          terminate(finalStatus, /* ackDone */ true);
        },

        onFailed: (data) => {
          const errMsg =
            (data as { message?: string; error?: string })?.message ??
            (data as { message?: string; error?: string })?.error ??
            "Stream failed";
          console.warn("[perf] failed %s error=%s", thread_id, errMsg);
          patch(thread_id, { error: errMsg });
          // failed/cancelled are terminal task events but not `done`-path;
          // backend will still emit `done` after these, but sessionClosed will
          // be true by then so the `done` handler becomes a no-op.
          terminate("failed");
        },

        onCancelled: () => {
          console.info("[perf] cancelled confirmed %s", thread_id);
          terminate("cancelled");
        },

        onClose: () => {
          if (!sessionClosed) {
            sessionClosed = true;
            console.warn("[perf] connection closed unexpectedly %s", thread_id);
            patch(thread_id, { status: "failed", error: "Connection closed unexpectedly", closed: true });
          }
        },
      });

      // Register cleanup for freezeAll and the last-resort safety timeout.
      // dequeue() removes both when a terminal event fires.
      esCleanup = cleanup;
      cleanups.current.set(thread_id, cleanup);
      const sessionTimeoutMs = config.timeoutSecs * 1000;
      const tid = setTimeout(() => {
        // Immediately close the session locally so metrics freeze right away,
        // then notify the backend so it tears down the worker.
        // onDone / onPerfTestStopped are guarded by sessionClosed and become no-ops.
        if (!sessionClosed) {
          sessionClosed = true;
          dequeue();
          if (config.testMode === "throughput" && tokensReceived < config.tokenCount) {
            console.warn(
              "[perf] safety-timeout fired: received=%d expected=%d gap=%d thread_id=%s",
              tokensReceived, config.tokenCount, config.tokenCount - tokensReceived, thread_id,
            );
            probeBackend("safety_timeout");
          }
          closeSession(thread_id, "timeout");
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
