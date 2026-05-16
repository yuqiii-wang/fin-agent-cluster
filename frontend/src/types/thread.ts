/** Thread-level types aligned to backend users/schemas.py. */

import type { GraphTopology } from './topology';
import type { NodeInfo } from './node';

/** Centrifugo connection bootstrap info bundled with a new query submission. */
export interface SseInfo {
  ws_url: string;
  connection_token: string;
  subscription_token: string;
  channel: string;
}

/** Full thread status returned by POST /query and GET /threads/{id}. */
export interface QueryResponse {
  thread_id: string;
  status: string;
  query?: string;
  answer?: string;
  error?: string;
  created_at?: string;
  completed_at?: string;
  /** Present only on initial query submission — SSE notification channel. */
  sse?: SseInfo;
  /** Present only on initial query submission — LLM streaming channel. */
  llm?: SseInfo;
  /** Full compiled graph topology, present on initial query submission. */
  topology?: GraphTopology;
  /** Present only on re-explore response — the new fork version number. */
  fork_version?: number | null;
}

/** Compact thread record returned by history / active-thread endpoints. */
export interface ThreadSummary {
  thread_id: string;
  query: string;
  status: string;
  created_at: string;
  completed_at?: string;
  answer?: string;
}

/** Version graph data returned by GET /threads/{id}/version/{version_id}. */
export interface VersionGraphResponse {
  version: number;
  thread_id: string;
  /** The fork-point node that started this branch; null for version 0. */
  fork_node: NodeInfo | null;
  /** The version this branch was forked from; null for version 0. */
  source_version: number | null;
  /** All nodes that executed in this version. */
  nodes: NodeInfo[];
}
