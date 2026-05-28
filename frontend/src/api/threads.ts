/**
 * Threads API client — wraps all /api/v1/threads/* and /api/v1/auth/centrifugo/* calls.
 */

import type { CentrifugoTokenResponse, GraphTopology, NodeInfo, NodeMeta, QueryResponse, TaskInfo, ThreadSummary, VersionGraphResponse, AgentCapabilities, AgentStepStatesResponse, Skill, NodeSkillsResponse } from '../types';
import { getStoredToken } from './auth';

/** API error that preserves the HTTP status code. */
export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

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

export async function getTask(threadId: string, taskId: string): Promise<TaskInfo> {
  const res = await fetch(`${BASE}/threads/${threadId}/tasks/${taskId}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Get task failed: ${res.status}`);
  return res.json();
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

export async function getGraphTopology(): Promise<GraphTopology> {
  const res = await fetch(`${BASE}/graph/topology`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Get graph topology failed: ${res.status}`);
  return res.json();
}

export async function fetchNodeMetas(): Promise<NodeMeta[]> {
  const res = await fetch(`${BASE}/graph/node-metas`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Get node metas failed: ${res.status}`);
  return res.json();
}

export async function fetchNodeSkills(): Promise<NodeSkillsResponse[]> {
  const res = await fetch(`${BASE}/graph/node-skills`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Get node skills failed: ${res.status}`);
  return res.json();
}

/**
 * Resolve a UUID (thread_id / node_id / task_id) to its parent ThreadSummary.
 * Returns null if not found or UUID is not owned by this user.
 */
export async function searchByUuid(uuid: string): Promise<ThreadSummary | null> {
  const res = await fetch(`${BASE}/queries/search?uuid=${encodeURIComponent(uuid)}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`UUID search failed: ${res.status}`);
  return res.json();
}

/**
 * Register the current user as actively viewing `threadId`.
 *
 * Sets the explicit Redis viewer flags on the backend so `stream_task` can
 * detect viewer presence without relying on Centrifugo WebSocket timing.
 * Fire-and-forget — errors are swallowed; the backend defaults to True on miss.
 */
export async function setThreadViewer(threadId: string): Promise<void> {
  try {
    await fetch(`${BASE}/threads/${threadId}/viewer`, {
      method: 'PUT',
      headers: authHeaders(),
    });
  } catch {
    // Non-fatal — backend defaults to True for viewer detection on error.
  }
}

/**
 * Clear the viewer flags for `threadId`.
 *
 * Called when the Centrifugo SSE subscription is torn down (thread completed,
 * navigation away, page unload).  Removing stale flags prevents the backend
 * from entering the full ACK retry loop when no subscriber is present.
 * Fire-and-forget — errors are swallowed.
 */
export async function clearThreadViewer(threadId: string): Promise<void> {
  try {
    await fetch(`${BASE}/threads/${threadId}/viewer`, {
      method: 'DELETE',
      headers: authHeaders(),
    });
  } catch {
    // Non-fatal.
  }
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

export async function pauseTask(threadId: string, taskId: string): Promise<void> {
  const res = await fetch(`${BASE}/threads/${threadId}/tasks/${taskId}/pause`, {
    method: 'POST',
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Pause task failed: ${res.status}`);
}

export async function retryTask(
  threadId: string,
  taskId: string,
  mode: 'restart' | 'compact_and_continue' = 'restart',
): Promise<TaskInfo> {
  const res = await fetch(`${BASE}/threads/${threadId}/tasks/${taskId}/retry`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ mode }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Retry task failed: ${res.status}`);
  }
  return res.json();
}

export async function retryFreshTask(threadId: string, taskId: string): Promise<TaskInfo> {
  const res = await fetch(`${BASE}/threads/${threadId}/tasks/${taskId}/retry-fresh`, {
    method: 'POST',
    headers: authHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Retry fresh task failed: ${res.status}`);
  }
  return res.json();
}

export async function retryRestartTask(threadId: string, taskId: string): Promise<TaskInfo> {
  const res = await fetch(`${BASE}/threads/${threadId}/tasks/${taskId}/retry-restart`, {
    method: 'POST',
    headers: authHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Retry restart task failed: ${res.status}`);
  }
  return res.json();
}

export async function continueTask(threadId: string, taskId: string): Promise<TaskInfo> {
  const res = await fetch(`${BASE}/threads/${threadId}/tasks/${taskId}/continue`, {
    method: 'POST',
    headers: authHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Continue task failed: ${res.status}`);
  }
  return res.json();
}

/**
 * Fork the graph at the checkpoint just before nodeId ran and re-execute.
 *
 * @param inputOverride - Optional GraphState field overrides to inject into
 *   the forked checkpoint before dispatching.  Keys must be valid GraphState
 *   field names; values replace the corresponding state entries.
 */
export async function reExploreNode(
  threadId: string,
  nodeId: string,
  inputOverride?: Record<string, unknown>,
): Promise<QueryResponse> {
  const res = await fetch(`${BASE}/threads/${threadId}/nodes/${nodeId}/re-explore`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ input_override: inputOverride ?? null }),
  });
  if (!res.ok) throw new ApiError(res.status, `Re-explore failed: ${res.status}`);
  return res.json();
}

export async function invalidateNodeCache(threadId: string, nodeId: string): Promise<{ invalidated: number }> {
  const res = await fetch(`${BASE}/threads/${threadId}/nodes/${nodeId}/invalidate-cache`, {
    method: 'POST',
    headers: authHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Invalidate node cache failed: ${res.status}`);
  }
  return res.json();
}

/**
 * Fetch version graph data for a specific fork generation.
 *
 * Version 0 = original run (no fork node).
 * Version N > 0 = re-explore branch; includes the fork node and all branch nodes.
 */
export async function getVersionGraph(threadId: string, version: number): Promise<VersionGraphResponse> {
  const res = await fetch(`${BASE}/threads/${threadId}/version/${version}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Get version graph failed: ${res.status}`);
  return res.json();
}

// ── Agent capability endpoints ─────────────────────────────────────────────

export async function getAgentCapabilities(threadId: string, nodeId: string): Promise<AgentCapabilities> {
  const res = await fetch(`${BASE}/threads/${threadId}/nodes/${nodeId}/agent/capabilities`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Get agent capabilities failed: ${res.status}`);
  return res.json();
}

export async function addAgentSkill(
  threadId: string,
  nodeId: string,
  summary: string,
  instructions: string,
): Promise<Skill> {
  const res = await fetch(`${BASE}/threads/${threadId}/nodes/${nodeId}/agent/skills`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ summary, instructions }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Add skill failed: ${res.status}`);
  }
  return res.json();
}

export async function forgetAgentSkill(
  threadId: string,
  nodeId: string,
  skillId: string,
): Promise<void> {
  const res = await fetch(
    `${BASE}/threads/${threadId}/nodes/${nodeId}/agent/skills/${skillId}/forget`,
    { method: 'POST', headers: authHeaders() },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Forget skill failed: ${res.status}`);
  }
}

export async function forgetAgentMemory(
  threadId: string,
  nodeId: string,
  memoryId: string,
): Promise<void> {
  const res = await fetch(
    `${BASE}/threads/${threadId}/nodes/${nodeId}/agent/memory/${memoryId}/forget`,
    { method: 'POST', headers: authHeaders() },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Forget memory failed: ${res.status}`);
  }
}

export async function compactAgentMemory(
  threadId: string,
  nodeId: string,
  memoryIds: string[],
  summary: string,
): Promise<{ memory_id: string; status: string }> {
  const res = await fetch(`${BASE}/threads/${threadId}/nodes/${nodeId}/agent/memory/compact`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ memory_ids: memoryIds, summary }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Compact memory failed: ${res.status}`);
  }
  return res.json();
}

export async function getAgentStepStates(
  threadId: string,
  nodeId: string,
): Promise<AgentStepStatesResponse> {
  const res = await fetch(`${BASE}/threads/${threadId}/nodes/${nodeId}/agent/step-states`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Get agent step states failed: ${res.status}`);
  return res.json();
}
