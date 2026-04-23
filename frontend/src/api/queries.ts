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
 */
export async function submitPerfQuery(
  query: string,
  token: string,
  perfParams?: {
    perf_total_tokens?: number;
    perf_timeout_secs?: number;
    perf_test_mode?: string;
    perf_token_per_sec?: number;
  },
): Promise<QueryResponse> {
  const res = await fetch(`${BASE}/users/query`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json", "X-User-Token": token },
    body: JSON.stringify({ query, ...perfParams }),
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
