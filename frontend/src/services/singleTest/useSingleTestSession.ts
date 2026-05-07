/**
 * useSingleTestSession — dedicated hook for Single Test mode.
 *
 * Completely decoupled from the perf-test pipeline.  Sends one query,
 * opens the Centrifugo SSE stream, and dispatches graph events so
 * GraphVisualizationPanel can visualize node + task lifecycle in real time.
 *
 * Trigger phrase: ``"DO E2E TEST NOW"``
 *
 * Flow:
 *   1. sendRequest() → POST /users/query → get thread_id
 *   2. Immediately ACK → POST /users/query/{thread_id}/ack
 *   3. openStream(thread_id) → subscribe to Centrifugo channel
 *   4. Dispatch GraphEvent on every node_input / node_output / node_status /
 *      started / completed / failed / cancelled / done event.
 */

import { useCallback, useRef, useState } from "react";
import { ackQuery, resumeQuery, submitPerfQuery } from "../../api";
import { openSseStream, openTokenStream } from "../../api/stream";
import { sendDoneAck } from "../streaming/core";
import { useGraphStore } from "../../components/GraphVisualizationPanel/useGraphStore";
import type { GraphEvent, GraphNode } from "../../components/GraphVisualizationPanel/types";
import { useTokenBatchFlush } from "../streaming/core";

const SINGLE_TRIGGER = "DO E2E TEST NOW";

export type SingleTestStatus =
  | "idle"          // no request sent yet
  | "submitting"    // HTTP POST in flight
  | "streaming"     // SSE stream open
  | "done"          // session completed/failed/cancelled
  | "error";        // submit or stream error

export interface SingleTestSession {
  thread_id: string;
  status: SingleTestStatus;
  doneStatus?: string;
  error?: string;
}

export interface UseSingleTestSessionReturn {
  session: SingleTestSession | null;
  graphState: ReturnType<typeof useGraphStore>["graphState"];
  /** Accumulated LLM token streams keyed by task_id. */
  tokenStreams: Record<string, string>;
  /** Total token counts received keyed by task_id. */
  tokenCounts: Record<string, number>;
  sendRequest: () => Promise<void>;
  resumeRequest: () => void;
  reset: () => void;
  isActive: boolean;
  isPendingControl: boolean;
}

/**
 * Thin orchestrator for a single query SSE session.
 *
 * @param userToken  Guest user token from useGuestAuth.
 */
export function useSingleTestSession(userToken: string): UseSingleTestSessionReturn {
  const [session, setSession] = useState<SingleTestSession | null>(null);
  const [tokenStreams, setTokenStreams] = useState<Record<string, string>>({});
  const [tokenCounts, setTokenCounts] = useState<Record<string, number>>({});
  // onToken (LLM): append each character to stream text.
  const tokenStreamBufferRef = useRef<Record<string, string>>({});
  const tokenCountBufferRef = useRef<Record<string, number>>({});
  // onTokenBatch (concurrency): drain-based replace-path managed by the hook.
  const { onTokenBatch, drainBatch, resetBatch } = useTokenBatchFlush();
  const flushIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const { graphState, dispatchEvent, resetGraph } = useGraphStore();
  const cleanupRef = useRef<(() => void) | null>(null);
  const runIdRef = useRef(crypto.randomUUID());

  const isActive = session?.status === "submitting" || session?.status === "streaming";
  const isPendingControl = false;

  /** Dispatch a GraphEvent, typed. */
  const dispatch = useCallback((ev: GraphEvent) => dispatchEvent(ev), [dispatchEvent]);

  /**
   * Open (or re-open) the Centrifugo stream for the given thread_id and
   * wire up all graph event handlers.  Does NOT reset the graph store so
   * resumed runs continue painting the same DAG.
   *
   * @param thread_id  LangGraph thread UUID.
   * @param onReady    Optional callback fired once the subscription is active.
   *                   When provided, channel history is skipped (`recoverHistory:
   *                   false`) so stale `done` events from a previous run are not
   *                   re-processed.  The caller (resumeRequest) uses this to
   *                   fire resumeQuery only after the channel is subscribed,
   *                   guaranteeing no events are missed.
   */
  const openSessionStream = useCallback((thread_id: string, onReady?: () => void) => {
    // Tear down any existing stream first.
    cleanupRef.current?.();
    cleanupRef.current = null;

    if (flushIntervalRef.current != null) {
      clearInterval(flushIntervalRef.current);
      flushIntervalRef.current = null;
    }

    setSession((prev) => prev ? { ...prev, thread_id, status: "streaming" } : { thread_id, status: "streaming" });

    // Start 100ms flush interval for token streams.
    flushIntervalRef.current = setInterval(() => {
      const streamBuf = tokenStreamBufferRef.current;
      const countBuf = tokenCountBufferRef.current;
      const batch = drainBatch();
      const hasAppend = Object.keys(streamBuf).length > 0;
      const hasReplace = batch !== null;
      if (!hasAppend && !hasReplace) return;
      tokenStreamBufferRef.current = {};
      tokenCountBufferRef.current = {};
      setTokenStreams((prev) => {
        const next = { ...prev };
        for (const [id, text] of Object.entries(streamBuf)) next[id] = (next[id] ?? "") + text;
        if (batch) for (const [id, text] of Object.entries(batch.streams)) next[id] = text;
        return next;
      });
      setTokenCounts((prev) => {
        const next = { ...prev };
        for (const [id, delta] of Object.entries(countBuf)) next[id] = (next[id] ?? 0) + delta;
        if (batch) for (const [id, delta] of Object.entries(batch.counts)) next[id] = (next[id] ?? 0) + delta;
        return next;
      });
    }, 100);

    // Combined cleanup ref so onDone can tear down both subscriptions.
    const closeRef = { current: (() => {}) as () => void };

    const closeSse = openSseStream(thread_id, userToken, {
        onGraphTopologyInit: (data) => {
          const d = data as Record<string, unknown>;
          dispatch({
            type: "graph_topology_init",
            outer_nodes: (d["outer_nodes"] as any[]) ?? [],
            subgraphs: (d["subgraphs"] as Record<string, any>) ?? {},
          });
        },
        onNodeInput: (data) => {
          const d = data as Record<string, unknown>;
          const execId = d["node_execution_id"] as number;
          const nodeName = d["node_name"] as string;
          const parentIds = (d["parent_node_execution_ids"] as number[] | null) ?? [];
          console.log(
            `[sse:node_input] node=${nodeName} exec_id=${execId} parents=[${parentIds.join(",")}] thread=${thread_id}`,
          );
          dispatch({
            type: "node_input",
            node_execution_id: execId,
            node_name: nodeName,
            parent_node_execution_ids: parentIds,
            input: (d["input"] as Record<string, unknown>) ?? {},
            node_type: typeof d["node_type"] === "string" ? d["node_type"] : undefined,
            subgraph_parent: typeof d["subgraph_parent"] === "string" ? d["subgraph_parent"] : undefined,
            ts: typeof d["started_at_ms"] === "number" ? d["started_at_ms"] : Date.now(),
          });
        },
        onNodeOutput: (data) => {
          const d = data as Record<string, unknown>;
          console.log(
            `[sse:node_output] node=${d["node_name"]} exec_id=${d["node_execution_id"]} elapsed=${d["elapsed_ms"]}ms thread=${thread_id}`,
          );
          dispatch({
            type: "node_output",
            node_execution_id: d["node_execution_id"] as number,
            node_name: d["node_name"] as string,
            output: (d["output"] as Record<string, unknown>) ?? {},
            elapsed_ms: (d["elapsed_ms"] as number) ?? 0,
            ended_at_ms: typeof d["ended_at_ms"] === "number" ? d["ended_at_ms"] : undefined,
            ts: Date.now(),
          });
        },
        onNodeStatus: (data) => {
          const d = data as Record<string, unknown>;
          console.log(
            `[sse:node_status] node=${d["node_name"]} status=${d["status"]} node_id=${d["node_id"]} thread=${thread_id}`,
          );
          dispatch({
            type: "node_status",
            node_id: d["node_id"] as string,
            node_name: d["node_name"] as string,
            status: d["status"] as string,
            ended_at_ms: typeof d["ended_at_ms"] === "number" ? d["ended_at_ms"] : undefined,
            ts: Date.now(),
          });
        },
        onStarted: (data) => {
          const d = data as Record<string, unknown>;
          console.log(
            `[sse:task_started] task=${d["task_name"]} node=${d["node_name"]} task_id=${d["task_id"]} thread=${thread_id}`,
          );
          const { event: _e, task_id: _t, node_name: _n, task_name: _k, provider: _p, ...rest } = d;
          dispatch({
            type: "task_started",
            task_id: d["task_id"] as string,
            node_name: d["node_name"] as string,
            task_name: d["task_name"] as string,
            input: rest as Record<string, unknown>,
            ts: Date.now(),
          });
        },
        onCompleted: (data) => {
          const d = data as Record<string, unknown>;
          console.log(
            `[sse:task_completed] task=${d["task_name"]} node=${d["node_name"]} task_id=${d["task_id"]} thread=${thread_id}`,
          );
          dispatch({
            type: "task_terminal",
            task_id: d["task_id"] as string,
            node_name: d["node_name"] as string,
            task_name: d["task_name"] as string,
            status: "completed",
            output: d["output"],
            ts: Date.now(),
          });
        },
        onFailed: (data) => {
          const d = data as Record<string, unknown>;
          console.log(
            `[sse:task_failed] task=${d["task_name"]} node=${d["node_name"]} task_id=${d["task_id"]} thread=${thread_id}`,
          );
          dispatch({
            type: "task_terminal",
            task_id: d["task_id"] as string,
            node_name: d["node_name"] as string,
            task_name: d["task_name"] as string,
            status: "failed",
            output: d["output"],
            ts: Date.now(),
          });
        },
        onCancelled: (data) => {
          const d = (data ?? {}) as Record<string, unknown>;
          console.log(
            `[sse:task_cancelled] task=${d["task_name"]} node=${d["node_name"]} task_id=${d["task_id"]} thread=${thread_id}`,
          );
          dispatch({
            type: "task_terminal",
            task_id: (d["task_id"] as string) ?? "",
            node_name: (d["node_name"] as string) ?? "",
            task_name: (d["task_name"] as string) ?? "",
            status: "cancelled",
            output: d["output"],
            ts: Date.now(),
          });
        },
        onDone: (data) => {
          const d = data as Record<string, unknown>;
          const doneStatus = (d["status"] as string) ?? "completed";
          console.log(`[sse:done] status=${doneStatus} thread=${thread_id}`);
          dispatch({ type: "done", status: doneStatus, ts: Date.now() });
          setSession((prev) => prev ? { ...prev, status: "done", doneStatus } : prev);
          sendDoneAck(thread_id, userToken, doneStatus).catch(() => {});
          if (flushIntervalRef.current != null) {
            clearInterval(flushIntervalRef.current);
            flushIntervalRef.current = null;
          }
          closeRef.current();
          cleanupRef.current = null;
        },
        onClose: () => {
          setSession((prev) => {
            if (!prev || prev.status === "done") return prev;
            return { ...prev, status: "done", doneStatus: "disconnected" };
          });
          if (flushIntervalRef.current != null) {
            clearInterval(flushIntervalRef.current);
            flushIntervalRef.current = null;
          }
        },
        onSubscribed: onReady,
      }, { recoverHistory: !onReady });

    const closeToken = openTokenStream(thread_id, userToken, {
      onToken: (data) => {
        const d = data as { task_id: string; data: string };
        const taskId = d.task_id;
        const tok = d.data ?? "";
        if (!tok) return;
        tokenStreamBufferRef.current[taskId] = (tokenStreamBufferRef.current[taskId] ?? "") + tok;
        tokenCountBufferRef.current[taskId] = (tokenCountBufferRef.current[taskId] ?? 0) + 1;
      },
      onTokenBatch,
    });

    closeRef.current = () => { closeSse(); closeToken(); };
    cleanupRef.current = closeRef.current;
  }, [userToken, drainBatch, onTokenBatch, dispatch]);

  const sendRequest = useCallback(async () => {
    if (isActive) return;

    // Reset graph + generate fresh run ID to avoid dedup collision.
    resetGraph();
    runIdRef.current = crypto.randomUUID();

    setSession({ thread_id: "", status: "submitting" });

    try {
      const query = `${SINGLE_TRIGGER} [${runIdRef.current}]`;
      const res = await submitPerfQuery(query, userToken);
      const thread_id: string = res.thread_id;

      // Immediately ACK so LangGraph execution starts.
      ackQuery(thread_id, userToken).catch((err) =>
        console.warn("[single] ack failed thread_id=%s", thread_id, err),
      );

      openSessionStream(thread_id);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error("[single] submit failed:", err);
      if (flushIntervalRef.current != null) {
        clearInterval(flushIntervalRef.current);
        flushIntervalRef.current = null;
      }
      setSession({ thread_id: "", status: "error", error: msg });
    }
  }, [isActive, userToken, resetGraph, openSessionStream]);

  const resumeRequest = useCallback(() => {
    const thread_id = session?.thread_id;
    if (!thread_id || isActive) return;
    openSessionStream(thread_id, () => {
      resumeQuery(thread_id).catch((err) =>
        console.error("[single] resume failed:", err),
      );
    });
  }, [session, isActive, openSessionStream]);

  const reset = useCallback(() => {
    cleanupRef.current?.();
    cleanupRef.current = null;
    if (flushIntervalRef.current != null) {
      clearInterval(flushIntervalRef.current);
      flushIntervalRef.current = null;
    }
    tokenStreamBufferRef.current = {};
    tokenCountBufferRef.current = {};
    resetBatch();
    setTokenStreams({});
    setTokenCounts({});
    resetGraph();
    setSession(null);
  }, [resetGraph]);

  return { session, graphState, tokenStreams, tokenCounts, sendRequest, resumeRequest, reset, isActive, isPendingControl };
}
