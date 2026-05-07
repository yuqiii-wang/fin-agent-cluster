import type { NodeExecutionInfo, QueryResponse, SessionStatus } from "../types";
import { BASE } from "./config";

// ── System health ─────────────────────────────────────────────────────────────

export interface InstanceHealth {
  url: string;
  kind: "runner" | "assistant";
  healthy: boolean;
}

export interface SystemHealthResponse {
  all_healthy: boolean;
  total: number;
  healthy_count: number;
  instances: InstanceHealth[];
}

export async function fetchSystemHealth(): Promise<SystemHealthResponse> {
  const res = await fetch(`${BASE}/system/health`, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Queries ───────────────────────────────────────────────────────────────────

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
 * backend execution (no browser or intermediate cache reuse).
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

export async function fetchNodeExecutions(threadId: string, version?: number): Promise<NodeExecutionInfo[]> {
  const url = version !== undefined
    ? `${BASE}/users/query/${threadId}/nodes?version=${version}`
    : `${BASE}/users/query/${threadId}/nodes`;
  const res = await fetch(url);
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
 * Enable opt-in live streaming for a preview task (MOCK_ANALYSIS_PREVIEW).
 * Sets the Redis live flag and flushes the buffered token preview to Centrifugo.
 * After this call the task publishes new tokens live until it finishes.
 *
 * Returns the number of buffered tokens that were flushed (for diagnostics).
 */
export async function enableTaskStream(threadId: string, taskId: string): Promise<number> {
  const res = await fetch(
    `${BASE}/users/query/${threadId}/tasks/${taskId}/enable-stream`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const body = await res.json();
  return (body as { flushed: number }).flushed ?? 0;
}
