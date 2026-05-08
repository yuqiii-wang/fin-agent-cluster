/**
 * SSE lifecycle phase-transition handlers for perf-test sessions.
 *
 * createPhaseHandlers returns four handlers covering the two-phase
 * ingest/pub lifecycle and task bookkeeping:
 *   onQueryStatus    — phase progression (received → preparing → ingesting → digesting)
 *   onIngestComplete — ingest phase complete; captures ingest metrics
 *   onStarted        — captures node/stream/task IDs from mock_runner
 *   onCompleted      — captures mock_pub total_published; marks pub_status
 */

import type React from "react";
import type { SessionClosureState } from "./sessionState";
import type { ThreadSession, PerfTestConfig } from "../../../components/StreamingPerfTestPanel/types";
import { TERMINAL_STATUSES } from "../../../components/StreamingPerfTestPanel/types";
import { sendStatusAck } from "./lifecycle";

export interface PhaseHandlerDeps {
  thread_id: string;
  userToken: string;
  patch: (thread_id: string, delta: Partial<ThreadSession>) => void;
  setSessions: React.Dispatch<React.SetStateAction<ThreadSession[]>>;
  config: Pick<PerfTestConfig, "testMode" | "tokenCount">;
}

const PHASE_ORDER: Record<string, number> = {
  connecting: 0, received: 1, preparing: 2, ingesting: 3, digesting: 4,
};

const PHASE_TO_STATUS: Record<string, ThreadSession["status"]> = {
  received:  "received",
  preparing: "preparing",
  ingesting: "ingesting",
  digesting: "digesting",
};

/** Factory for SSE lifecycle phase-transition handlers. */
export function createPhaseHandlers(
  state: SessionClosureState,
  deps: PhaseHandlerDeps,
) {
  const { thread_id, userToken, patch, setSessions, config } = deps;

  const onQueryStatus = (data: unknown): void => {
    const d = data as { phase?: string; is_double_check?: boolean };
    const newStatus = PHASE_TO_STATUS[d.phase ?? ""];
    const prevStatus = state.sessionStatus;
    const currentOrder = PHASE_ORDER[state.sessionStatus] ?? -1;
    const newOrder = PHASE_ORDER[d.phase ?? ""] ?? -1;
    // Always ACK first so the verifier clears the re-send flag regardless.
    sendStatusAck(thread_id, d.phase!, userToken, d.is_double_check ?? false).catch(() => {});
    if (newStatus && newOrder >= currentOrder) {
      state.sessionStatus = newStatus; // keep closure in sync
      console.info("[perf] %s → %s (was=%s order %d→%d double_check=%s)", thread_id, newStatus, prevStatus, currentOrder, newOrder, d.is_double_check ?? false);
      // For throughput mode: set digest_start_ms when transitioning to "digesting".
      const digestNow = newStatus === "digesting" ? Date.now() : null;
      setSessions((prev) =>
        prev.map((s) => {
          if (s.thread_id !== thread_id || s.closed || TERMINAL_STATUSES.has(s.status)) return s;
          const digestPatch =
            digestNow !== null && s.test_mode === "throughput" && s.digest_start_ms == null
              ? { digest_start_ms: digestNow }
              : {};
          return { ...s, status: newStatus, ...digestPatch };
        })
      );
    } else if (newStatus) {
      // Phase blocked by ordering guard — verifier re-sent a stale phase.
      console.warn(
        "[perf] PHASE BLOCKED (regression guard) thread_id=%s phase=%s rejected currentStatus=%s (order %d >= %d required)",
        thread_id, d.phase, prevStatus, newOrder, currentOrder,
      );
    }
  };

  const onIngestComplete = (data: unknown): void => {
    const d = data as { stream_id?: string; node_id?: string; produced?: number; stop_reason?: string; ingest_ms?: number };
    const status = d.stop_reason === "timeout" ? "timeout" as const : "completed" as const;
    console.info(
      "[perf] ingest complete %s produced=%d stop_reason=%s ingest_ms=%d",
      thread_id, d.produced ?? 0, d.stop_reason ?? "ok", d.ingest_ms ?? 0,
    );
    // pub_start_ms marks the start of the pure-delivery phase — only meaningful
    // for throughput where ingest fully completes before Centrifugo begins delivering.
    const pubStartPatch = config.testMode === "throughput"
      ? { pub_start_ms: Date.now() }
      : {};
    patch(thread_id, {
      ingest_produced: d.produced,
      ingest_status: status,
      ingest_ms: d.ingest_ms,
      ...pubStartPatch,
    });
  };

  const onStarted = (data: unknown): void => {
    // Capture IDs emitted by the mock_runner node via extra_payload.
    const d = data as { node_id?: string; task_id?: string; stream_id?: string };
    if (d.node_id || d.task_id || d.stream_id) {
      if (d.stream_id) state.stream_id = d.stream_id;
      patch(thread_id, {
        node_id: d.node_id ?? null,
        task_id: d.task_id ?? null,
        stream_id: d.stream_id ?? null,
      });
    }
  };

  const onCompleted = (data: unknown): void => {
    const d = data as { task_name?: string; output?: Record<string, unknown> };
    const key = d?.task_name ?? "";
    console.info("[perf] task completed %s key=%s", thread_id, key);
    if (key === "MOCK_RUNNER_THROUGHPUT" || key === "MOCK_RUNNER_CONCURRENCY") {
      // Capture the authoritative published count from the backend task output.
      const backendPublished = d?.output?.["total_published"];
      if (typeof backendPublished === "number" && backendPublished > 0) {
        state.actualTokensExpected = backendPublished;
        console.info(
          "[perf] mock_pub completed total_published=%d (was config.tokenCount=%d) thread_id=%s",
          backendPublished, config.tokenCount, thread_id,
        );
      }
      patch(thread_id, { pub_status: "completed" });
    }
  };

  return { onQueryStatus, onIngestComplete, onStarted, onCompleted };
}
