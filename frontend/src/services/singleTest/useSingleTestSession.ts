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
import { replayFromNode, forkFromNode } from "../../api";
import { openStream } from "../../api/stream";
import { sendDoneAck } from "../streaming/core";
import { useGraphStore } from "../../components/GraphVisualizationPanel/useGraphStore";
import type { GraphEvent, GraphNode } from "../../components/GraphVisualizationPanel/types";
import { useTokenBatchFlush } from "../streaming/core";

const SINGLE_TRIGGER = "DO E2E TEST NOW";

/**
 * Compute node_execution_ids of all nodes that will be re-run when replaying
 * from `startName`.  The backend's checkpoint for `startName` is the snapshot
 * BEFORE `startName` (and all its siblings at the same fan-out level) ran.
 * So the pending set is everything EXCEPT the guaranteed-non-re-run ancestors.
 *
 * Algorithm: BFS *upward* from `startName` to find all ancestors (including
 * the start node itself), then mark every non-ancestor as pending.
 */
function getPendingExecIds(nodes: GraphNode[], startName: string): number[] {
  const startNode = nodes.find((n) => n.node_name === startName);
  if (!startNode) return [];

  // BFS upward to collect ancestors (nodes whose checkpoints are NOT reset).
  const ancestors = new Set<number>();
  const upQueue = [...startNode.parent_node_execution_ids];
  while (upQueue.length > 0) {
    const pid = upQueue.shift()!;
    if (ancestors.has(pid)) continue;
    ancestors.add(pid);
    const parentNode = nodes.find((n) => n.node_execution_id === pid);
    if (parentNode) upQueue.push(...parentNode.parent_node_execution_ids);
  }

  // Everything that is NOT an ancestor will be re-run → mark pending.
  return nodes
    .filter((n) => !ancestors.has(n.node_execution_id))
    .map((n) => n.node_execution_id);
}

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
  /** Replay graph from a specific node's last checkpoint (time-travel). */
  replayRequest: (nodeName: string) => void;
  /** Fork graph from a specific node's checkpoint into a new independent thread. */
  forkRequest: (nodeName: string) => void;
  reset: () => void;
  isActive: boolean;
  /** True while a control action (replay/fork) is awaiting the first backend ack. */
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
  // Ref-based guard: prevents a second replayRequest from firing while a replay
  // is inflight (between click and the first SSE event that updates node status).
  // Using a ref (not state) so the guard is synchronous and not affected by
  // React's async state-update batching.
  const replayInFlightRef = useRef(false);
  // Same pattern for fork.
  const forkInFlightRef = useRef(false);
  // State-based pending flag for UI feedback (spinner / disable buttons).
  const [replayPending, setReplayPending] = useState(false);
  const [forkPending, setForkPending] = useState(false);
  // Ref mirror of pending state for use inside callbacks without stale closures.
  const replayPendingRef = useRef(false);
  const forkPendingRef = useRef(false);
  // Non-stale reference to current graph nodes (updated each render).
  const graphNodesRef = useRef<GraphNode[]>([]);
  graphNodesRef.current = graphState.nodes;

  const isActive = session?.status === "submitting" || session?.status === "streaming";
  const isPendingControl = replayPending || forkPending;

  /** Dispatch a GraphEvent, typed. */
  const dispatch = useCallback((ev: GraphEvent) => dispatchEvent(ev), [dispatchEvent]);

  /**
   * Open (or re-open) the Centrifugo stream for the given thread_id and
   * wire up all graph event handlers.  Does NOT reset the graph store so
   * resumed runs continue painting the same DAG.
   *
   * @param thread_id  LangGraph thread UUID.
   * @param onReady    Optional callback fired once the subscription is active.
   *                   When provided, history replay is skipped (`recoverHistory:
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

    const cleanup = openStream(thread_id, userToken, {
        onToken: (data) => {
          const d = data as { task_id: string; data: string };
          const taskId = d.task_id;
          const tok = d.data ?? "";
          if (!tok) return;
          tokenStreamBufferRef.current[taskId] = (tokenStreamBufferRef.current[taskId] ?? "") + tok;
          tokenCountBufferRef.current[taskId] = (tokenCountBufferRef.current[taskId] ?? 0) + 1;
        },
        onTokenBatch,
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
            ts: typeof d["started_at_ms"] === "number" ? d["started_at_ms"] : Date.now(),
          });
          // Clear pending control on first node_input ack (replay/fork started)
          if (replayPendingRef.current) {
            console.log(`[sse:replay_ack] first node_input after replay: node=${nodeName} thread=${thread_id}`);
            replayPendingRef.current = false;
            setReplayPending(false);
          }
          if (forkPendingRef.current) {
            console.log(`[sse:fork_ack] first node_input after fork: node=${nodeName} thread=${thread_id}`);
            forkPendingRef.current = false;
            setForkPending(false);
          }
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
          // Collect extra_payload fields as task input (everything except known fields)
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
          replayInFlightRef.current = false;
          forkInFlightRef.current = false;
          replayPendingRef.current = false;
          forkPendingRef.current = false;
          setReplayPending(false);
          setForkPending(false);
          // Send done-ack so the assistant can clean up session state.
          sendDoneAck(thread_id, userToken, doneStatus).catch(() => {});
          if (flushIntervalRef.current != null) {
            clearInterval(flushIntervalRef.current);
            flushIntervalRef.current = null;
          }
          cleanup();
          cleanupRef.current = null;
        },
        onClose: () => {
          replayInFlightRef.current = false;
          forkInFlightRef.current = false;
          setSession((prev) => {
            if (!prev || prev.status === "done") return prev;
            return { ...prev, status: "done", doneStatus: "disconnected" };
          });
          if (flushIntervalRef.current != null) {
            clearInterval(flushIntervalRef.current);
            flushIntervalRef.current = null;
          }
        },
        // When onReady is provided (resume path), fire it once subscribed.
        onSubscribed: onReady,
      }, { recoverHistory: !onReady });

      cleanupRef.current = cleanup;
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

  /**
   * Resume the current cancelled/failed thread without resetting the graph.
   * Opens a fresh Centrifugo subscription (no history replay to avoid
   * re-processing the previous run's `done` event), then fires `resumeQuery`
   * only once the subscription is active so no events are missed.
   */
  const resumeRequest = useCallback(() => {
    const thread_id = session?.thread_id;
    if (!thread_id || isActive) return;
    openSessionStream(thread_id, () => {
      resumeQuery(thread_id).catch((err) =>
        console.error("[single] resume failed:", err),
      );
    });
  }, [session, isActive, openSessionStream]);

  /**
   * Replay from a specific node's last checkpoint (LangGraph time-travel).
   * Opens a fresh Centrifugo subscription first, then fires `replayFromNode`
   * only once subscribed so no lifecycle events are missed.
   *
   * A ref-based in-flight guard prevents rapid double-clicks from spawning a
   * second replay before the first one's SSE events update the node status.
   * Pending state is set immediately so the UI disables action buttons and
   * marks the replayed node + descendants as grey (pending) in the DAG.
   */
  const replayRequest = useCallback((nodeName: string) => {
    const thread_id = session?.thread_id;
    if (!thread_id || isActive) return;
    // Synchronous ref guard: React state batching can make `isActive` stale for
    // one render cycle after the first click.  The ref is always up-to-date.
    if (replayInFlightRef.current) return;
    replayInFlightRef.current = true;
    replayPendingRef.current = true;
    setReplayPending(true);
    // Optimistically mark the replayed node and all non-ancestor nodes as pending
    // (grey) so the DAG shows them as "awaiting re-execution" before SSE events
    // arrive.  Includes siblings (e.g. mock_stats when replaying from mock_news)
    // since the backend resets the checkpoint before both ran.
    const pendingIds = getPendingExecIds(graphNodesRef.current, nodeName);
    if (pendingIds.length > 0) {
      dispatch({ type: "nodes_set_pending", node_execution_ids: pendingIds });
    }
    openSessionStream(thread_id, () => {
      replayFromNode(thread_id, nodeName)
        .catch((err) => {
          console.error("[single] replay failed:", err);
          replayInFlightRef.current = false;
          replayPendingRef.current = false;
          setReplayPending(false);
        });
    });
  }, [session, isActive, openSessionStream, dispatch]);

  /**
   * Fork from a specific node's checkpoint into a completely new thread.
   * The original thread is untouched.  The session switches to the new thread.
   * Pending state is set immediately so the UI disables action buttons.
   */
  const forkRequest = useCallback((nodeName: string) => {
    const thread_id = session?.thread_id;
    if (!thread_id || isActive) return;
    if (forkInFlightRef.current) return;
    forkInFlightRef.current = true;
    forkPendingRef.current = true;
    setForkPending(true);
    // Fork creates new thread_id — reset graph for fresh visualization.
    resetGraph();
    forkFromNode(thread_id, nodeName)
      .then((res) => {
        const new_thread_id = res.new_thread_id;
        setSession({ thread_id: new_thread_id, status: "streaming" });
        openSessionStream(new_thread_id);
      })
      .catch((err) => {
        console.error("[single] fork failed:", err);
        forkInFlightRef.current = false;
        forkPendingRef.current = false;
        setForkPending(false);
      });
  }, [session, isActive, resetGraph, openSessionStream]);

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
    replayPendingRef.current = false;
    forkPendingRef.current = false;
    setReplayPending(false);
    setForkPending(false);
  }, [resetGraph]);

  return { session, graphState, tokenStreams, tokenCounts, sendRequest, resumeRequest, replayRequest, forkRequest, reset, isActive, isPendingControl };
}
