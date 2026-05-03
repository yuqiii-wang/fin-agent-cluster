import type { NodeExecutionInfo, QueryResponse, SessionStatus } from "../types";
import { BASE } from "./config";

// ── Queries ──────────────────────────────────────────────────────────────────

export async function submitQuery(
  query: string,
  token: string,
  perfParams?: { perf_total_tokens?: number; perf_timeout_secs?: number },
): Promise<QueryResponse> {
  const res = await fetch(`${BASE}/users/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-User-Token": token },
    body: JSON.stringify({ query, ...perfParams }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

/**
 * Submit a perf-test query with cache disabled so each stream gets a fresh
 * backend execution (no browser or intermediate cache replay).
 *
 * Test parameters (test_mode, total_tokens, timeout_secs, token_per_sec) are
 * encoded as JSON in the query string by :func:`buildPerfQuery` in
 * useSessionManager so the backend mock_runner node can parse them without
 * any API schema change.
 */
export async function submitPerfQuery(
  query: string,
  token: string,
): Promise<QueryResponse> {
  const res = await fetch(`${BASE}/users/query`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json", "X-User-Token": token },
    body: JSON.stringify({ query }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export async function fetchTasks(threadId: string): Promise<SessionStatus> {
  const res = await fetch(`${BASE}/users/query/${threadId}/tasks`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function fetchNodeExecutions(threadId: string): Promise<NodeExecutionInfo[]> {
  const res = await fetch(`${BASE}/users/query/${threadId}/nodes`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/**
 * Fetch the current status of a submitted query.
 *
 * Routes to the assistant upstream (read-only, no LangGraph involvement).
 * Used by the frontend to proactively check query state when the Centrifugo
 * subscription becomes active but no lifecycle events have been received yet
 * (e.g. query already completed before the WebSocket connected).
 */
export async function fetchQueryStatus(threadId: string): Promise<QueryResponse> {
  const res = await fetch(`${BASE}/users/query/${threadId}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function cancelQuery(threadId: string, reason: "user" | "timeout" = "user"): Promise<void> {
  const url = reason === "timeout"
    ? `${BASE}/users/query/${threadId}/cancel?reason=timeout`
    : `${BASE}/users/query/${threadId}/cancel`;
  const res = await fetch(url, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
}

export async function cancelNode(threadId: string, nodeId: string): Promise<void> {
  const res = await fetch(`${BASE}/users/query/${threadId}/nodes/${nodeId}/cancel`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
}

export async function resumeQuery(threadId: string): Promise<QueryResponse> {
  const res = await fetch(`${BASE}/users/query/${threadId}/resume`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export async function pauseQuery(threadId: string): Promise<QueryResponse> {
  const res = await fetch(`${BASE}/users/query/${threadId}/pause`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export async function cancelTaskByUuid(
  threadId: string,
  taskId: string,
  nodeId?: string,
): Promise<void> {
  const url = nodeId
    ? `${BASE}/users/query/${threadId}/tasks/${taskId}/cancel?node_id=${encodeURIComponent(nodeId)}`
    : `${BASE}/users/query/${threadId}/tasks/${taskId}/cancel`;
  const res = await fetch(url, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
}

/**
 * Acknowledge a received query, triggering backend LangGraph execution.
 *
 * Must be called after the client receives a `query_received` SSE event.
 * Returns `{thread_id, status: "running"}` on success.
 * Idempotent — safe to call multiple times until `query_ack_confirmed` is received.
 */
export async function ackQuery(threadId: string, token: string): Promise<QueryResponse> {
  const res = await fetch(`${BASE}/users/query/${threadId}/ack`, {
    method: "POST",
    headers: { "X-User-Token": token },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

/**
 * Signal the backend that this concurrency perf stream has reached stable TPS.
 * The backend will conclude the ingest loop cleanly and emit `perf_test_complete`
 * (instead of `perf_test_stopped`) so the session closes as "completed".
 * Fire-and-forget — resolves immediately once the HTTP response returns.
 */
export async function stablePerfStream(threadId: string, streamId: string, userToken: string): Promise<void> {
  const url = `${BASE}/users/query/${threadId}/perf-stable?stream_id=${encodeURIComponent(streamId)}`;
  const res = await fetch(url, {
    method: "POST",
    cache: "no-store",
    headers: { "X-User-Token": userToken },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
}

/**
 * Replay a completed/paused/cancelled query from a specific node's last
 * LangGraph checkpoint (time-travel replay).
 *
 * The backend finds the checkpoint where *nodeName* is in `snapshot.next`
 * and re-invokes the graph from that point.  Nodes before *nodeName* are
 * replayed from cache; the target node and its descendants execute fresh.
 */
export async function replayFromNode(threadId: string, nodeName: string): Promise<QueryResponse> {
  const res = await fetch(`${BASE}/users/query/${threadId}/replay`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ node_name: nodeName }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail?.message ?? err.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export interface ForkFromNodeResponse {
  source_thread_id: string;
  new_thread_id: string;
  node_name: string;
  status: string;
}

/**
 * Fork a completed/paused/cancelled query from a specific node's checkpoint
 * into a completely new independent thread (LangGraph time-travel fork).
 *
 * Unlike replay (same thread), fork creates a new thread_id.  The original
 * thread is not modified.  The caller should subscribe to the new thread's
 * Centrifugo channel.
 */
export async function forkFromNode(threadId: string, nodeName: string): Promise<ForkFromNodeResponse> {
  const res = await fetch(`${BASE}/users/query/${threadId}/fork`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ node_name: nodeName }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail?.message ?? err.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}
