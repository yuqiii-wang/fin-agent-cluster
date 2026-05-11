/**
 * Threads API client — wraps all /api/v1/threads/* and /api/v1/auth/centrifugo/* calls.
 */

import type { CentrifugoTokenResponse, NodeInfo, QueryResponse, TaskInfo, ThreadSummary } from '../types';
import { getStoredToken } from './auth';

const BASE = '/api/v1';

function authHeaders(): Record<string, string> {
  const token = getStoredToken();
  return {
    'Content-Type': 'application/json',
    ...(token ? { 'X-User-Token': token } : {}),
  };
}

export async function submitQuery(query: string): Promise<QueryResponse> {
  const res = await fetch(`${BASE}/threads/query`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ query }),
  });
  if (!res.ok) throw new Error(`Submit query failed: ${res.status}`);
  return res.json();
}

export async function getThread(threadId: string): Promise<QueryResponse> {
  const res = await fetch(`${BASE}/threads/${threadId}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Get thread failed: ${res.status}`);
  return res.json();
}

export async function getNodes(threadId: string): Promise<NodeInfo[]> {
  const res = await fetch(`${BASE}/threads/${threadId}/nodes`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Get nodes failed: ${res.status}`);
  return res.json();
}

export async function getTasks(threadId: string): Promise<TaskInfo[]> {
  const res = await fetch(`${BASE}/threads/${threadId}/tasks`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Get tasks failed: ${res.status}`);
  const data = await res.json();
  return Array.isArray(data) ? data : (data.tasks ?? []);
}

export async function getLlmToken(threadId: string): Promise<CentrifugoTokenResponse> {
  const res = await fetch(`${BASE}/auth/centrifugo/llm-token?thread_id=${threadId}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`LLM token failed: ${res.status}`);
  return res.json();
}

export async function getSseToken(threadId: string): Promise<CentrifugoTokenResponse> {
  const res = await fetch(
    `${BASE}/auth/centrifugo/sse-notification?thread_id=${threadId}`,
    { headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`SSE token failed: ${res.status}`);
  return res.json();
}

export async function sendAck(
  threadId: string,
  scope: string,
  ackKey: string,
): Promise<void> {
  // ACK is sent via Centrifugo RPC from the frontend Centrifuge client, not REST.
  // This helper is a no-op placeholder — RPC is handled in useCentrifugoSse.
  void threadId; void scope; void ackKey;
}

export async function getHistory(limit = 40, offset = 0): Promise<ThreadSummary[]> {
  const res = await fetch(`${BASE}/auth/me/history?limit=${limit}&offset=${offset}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Get history failed: ${res.status}`);
  return res.json();
}

export async function getActiveThread(): Promise<ThreadSummary | null> {
  const res = await fetch(`${BASE}/auth/me/active`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Get active thread failed: ${res.status}`);
  const data = await res.json();
  return data ?? null;
}

export async function cancelThread(threadId: string): Promise<void> {
  const res = await fetch(`${BASE}/threads/${threadId}/cancel`, {
    method: 'POST',
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Cancel thread failed: ${res.status}`);
}

export async function cancelNode(threadId: string, nodeId: string): Promise<void> {
  const res = await fetch(`${BASE}/threads/${threadId}/nodes/${nodeId}/cancel`, {
    method: 'POST',
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Cancel node failed: ${res.status}`);
}

export async function cancelTask(threadId: string, taskId: string, nodeId?: string): Promise<void> {
  const params = nodeId ? `?node_id=${encodeURIComponent(nodeId)}` : '';
  const res = await fetch(`${BASE}/threads/${threadId}/tasks/${taskId}/cancel${params}`, {
    method: 'POST',
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Cancel task failed: ${res.status}`);
}
