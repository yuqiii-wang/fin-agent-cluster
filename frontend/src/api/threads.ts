/**
 * API helpers for GET /api/v1/threads/* endpoints.
 *
 * These calls never trigger a LangGraph graph run — they read directly from
 * the database or publish events to Centrifugo.
 */

import type {
  EmitEventRequest,
  EmitEventResponse,
  LlmResponseList,
  ResyncResponse,
  ThreadListResponse,
  ThreadStateResponse,
  UpdateThreadStatusRequest,
  UpdateThreadStatusResponse,
} from "../types";
import { BASE } from "./config";

// ── Read endpoints ────────────────────────────────────────────────────────────

/**
 * Fetch a paginated list of threads for the authenticated user.
 *
 * @param token   X-User-Token for the authenticated user.
 * @param status  Comma-separated status filter, e.g. "running,completed".
 * @param limit   Page size (1–100).
 * @param offset  Row offset.
 */
export async function fetchThreads(
  token: string,
  status?: string,
  limit = 20,
  offset = 0,
): Promise<ThreadListResponse> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (status) params.set("status", status);
  const res = await fetch(`${BASE}/threads?${params}`, {
    headers: { "X-User-Token": token },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as Record<string, string>).detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

/**
 * Fetch LLM completion records for a thread from fin_agents.llm_responses.
 *
 * @param threadId  LangGraph thread UUID.
 * @param limit     Max records (1–200).
 * @param offset    Row offset.
 */
export async function fetchThreadLlmResponses(
  threadId: string,
  limit = 50,
  offset = 0,
): Promise<LlmResponseList> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  const res = await fetch(`${BASE}/threads/${encodeURIComponent(threadId)}/llm-responses?${params}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as Record<string, string>).detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

/**
 * Fetch the latest LangGraph checkpoint state for a thread.
 *
 * Reads the PostgreSQL checkpointer — no graph nodes execute.
 *
 * @param threadId  LangGraph thread UUID.
 */
export async function fetchThreadState(threadId: string): Promise<ThreadStateResponse> {
  const res = await fetch(`${BASE}/threads/${encodeURIComponent(threadId)}/state`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as Record<string, string>).detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

// ── Write / event endpoints ───────────────────────────────────────────────────

/**
 * Update a thread's status in DB without triggering a graph run.
 *
 * When `emit_event` is true (default), also publishes a `query_status`
 * Centrifugo event so subscribed clients reflect the change immediately.
 *
 * @param threadId  LangGraph thread UUID.
 * @param body      `{ status, error?, emit_event? }`
 * @param token     X-User-Token for the authenticated user.
 */
export async function updateThreadStatus(
  threadId: string,
  body: UpdateThreadStatusRequest,
  token: string,
): Promise<UpdateThreadStatusResponse> {
  const res = await fetch(`${BASE}/threads/${encodeURIComponent(threadId)}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-User-Token": token },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as Record<string, string>).detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

/**
 * Publish a lifecycle event to the thread's Centrifugo channel.
 *
 * Does not modify any database rows.  High-frequency stream events
 * (`token`, `perf_token`) are rejected by the backend.
 *
 * @param threadId  LangGraph thread UUID.
 * @param body      `{ event, payload? }`
 * @param token     X-User-Token for the authenticated user.
 */
export async function emitThreadEvent(
  threadId: string,
  body: EmitEventRequest,
  token: string,
): Promise<EmitEventResponse> {
  const res = await fetch(`${BASE}/threads/${encodeURIComponent(threadId)}/events/emit`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-User-Token": token },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as Record<string, string>).detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

/**
 * Re-emit current thread and task states as Centrifugo events.
 *
 * Intended for clients that reconnect mid-session and need to rebuild
 * their local state without replaying the full channel history.
 *
 * @param threadId  LangGraph thread UUID.
 * @param token     X-User-Token for the authenticated user.
 */
export async function resyncThread(
  threadId: string,
  token: string,
): Promise<ResyncResponse> {
  const res = await fetch(`${BASE}/threads/${encodeURIComponent(threadId)}/events/resync`, {
    method: "POST",
    headers: { "X-User-Token": token },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as Record<string, string>).detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}
