/** Shared TypeScript types matching backend Pydantic schemas. */

export interface SseInfo {
  ws_url: string;
  connection_token: string;
  subscription_token: string;
  channel: string;
}

export interface QueryResponse {
  thread_id: string;
  status: string;
  query?: string;
  answer?: string;
  error?: string;
  created_at?: string;
  completed_at?: string;
  sse?: SseInfo;
  llm?: SseInfo;
}

export interface NodeInfo {
  node_id: string;
  thread_id: string;
  node_name: string;
  status: string;
  type: string; // "Typical" | "Reference" | "Subgraph"
  parent_node_id?: string;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  started_at?: string;
  elapsed_ms: number;
  updated_at?: string;
}

export interface TaskInfo {
  task_id: string;
  thread_id: string;
  node_id?: string;
  node_name: string;
  task_name: string;
  status: string;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

export interface GuestAuthResponse {
  id: string;
  username: string;
  display_name?: string;
  email?: string;
  email_verified: boolean;
  avatar_url?: string;
  auth_type: string;
  is_new: boolean;
}

export interface CentrifugoTokenResponse {
  ws_url: string;
  connection_token: string;
  subscription_token: string;
  shard_index: number;
  channel: string;
}

/** SSE event pushed by the backend via Centrifugo. */
export interface SseEvent {
  event: string;
  thread_id?: string;
  node_id?: string;
  node_name?: string;
  task_id?: string;
  task_name?: string;
  status?: string;
  token?: string;
  seq?: number;
  total_tokens?: number;
  total_seq?: number;
  /** Present on ``ack_confirmed`` events — the ack_key that was confirmed. */
  ack_key?: string;
  [key: string]: unknown;
}
