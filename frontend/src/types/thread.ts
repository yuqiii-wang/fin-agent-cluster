/** Thread-level types aligned to backend users/schemas.py. */

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
