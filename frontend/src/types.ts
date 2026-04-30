/** Shared TypeScript types mirroring the backend schemas. */

/** Guest user returned by POST /api/v1/auth/guest. */
export interface GuestUser {
  id: string;
  username: string;
  display_name: string | null;
  email: string | null;
  email_verified: boolean;
  avatar_url: string | null;
  auth_type: "guest" | "password" | "oauth";
  is_new: boolean;
}

/** Lightweight thread summary for the history panel. */
export interface ThreadSummary {
  thread_id: string;
  query: string;
  status: string;
  created_at: string;
  completed_at: string | null;
  answer: string | null;
}

/** Task key type classification metadata from GET /api/v1/tasks/meta. */
export interface TaskTypeMeta {
  /** Task keys that emit token-stream SSE events (LLM streaming). */
  llm_task_keys: string[];
  /** All other static literal task keys found in agent tasks modules. */
  all_task_keys: string[];
  /** Task keys that emit perf_token SSE events (silent metric aggregation, not shown as task output). */
  perf_token_task_keys: string[];
}

/** Metadata for one selectable technical indicator (from GET /api/v1/quant/indicators). */
export interface QuantIndicatorMeta {
  id: string;
  label: string;
  group: string;
  /** True = overlay on price chart; false = separate panel chart. */
  overlay: boolean;
  /** Response field names for each column, e.g. ["value"] or ["upper","middle","lower"]. */
  keys: string[];
}

/** Single data point returned by GET /api/v1/quant/stats/{symbol}/{granularity}. */
export interface QuantStatPoint {
  date: string;
  /** Map of key → numeric value (null when the DB row is NULL). */
  values: Record<string, number | null>;
}

/** Full response from the indicator stats endpoint. */
export interface QuantIndicatorSeries {
  symbol: string;
  granularity: string;
  indicator: string;
  meta: QuantIndicatorMeta;
  data: QuantStatPoint[];
  /** True when every data point contains only null values. */
  all_null: boolean;
}

/** Currency information for a traded symbol (from GET /api/v1/quant/symbol-currency/{symbol}). */
export interface CurrencyInfo {
  /** ISO 4217 code, e.g. "USD" */
  code: string;
  /** Full name, e.g. "US Dollar" */
  name: string;
  /** Display symbol, e.g. "$", "€", "¥" */
  symbol: string;
  /** Decimal places for price display */
  decimals: number;
}

export interface TaskInfo {
  id: number;
  thread_id: string;
  node_execution_id: number | null;
  node_name: string;
  task_key: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  /** Human-readable error message populated when status is 'failed'. */
  error?: string;
  /** Structured error code from the backend error registry (e.g. 'DB_INSERT_FAILED'). */
  error_code?: string;
  /** Human-readable description for error_code, embedded inline in the SSE payload. */
  error_description?: string;
}

export interface SessionStatus {
  thread_id: string;
  user_query_id: number;
  status: string;
  tasks: TaskInfo[];
}

export interface QueryResponse {
  thread_id: string;
  status: string;
  report: string | null;
  error: string | null;
}

/** A node group derived from tasks, keyed by node_name. */
export interface NodeGroup {
  node_name: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  tasks: TaskInfo[];
}

/** SSE event payloads */
export interface SseStarted {
  task_id: number;
  node_name: string;
  task_key: string;
  provider?: string;
}

export interface SseCompleted {
  task_id: number;
  node_name: string;
  task_key: string;
  output: Record<string, unknown>;
}

export interface SseFailed {
  task_id: number;
  node_name: string;
  task_key: string;
  output: Record<string, unknown>;
}

export interface SseCancelled {
  task_id: number;
  node_name: string;
  task_key: string;
  output: Record<string, unknown>;
}

export interface SseToken {
  task_id: number;
  token: string;
}

/** A chat message in the UI. */
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  thread_id?: string;
  status?: "running" | "completed" | "failed" | "cancelled";
  streamingCursor?: boolean;
  /** True when this message was produced by the streaming perf test. */
  isPerfTest?: boolean;
  nodes?: NodeGroup[];
}

/** Node-level input/output snapshot from the backend. */
export interface NodeExecutionInfo {
  id: number;
  node_name: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  started_at: string;
  elapsed_ms: number;
}

// ── Threads API (GET /api/v1/threads/*) ──────────────────────────────────────

/** Paginated list of thread summaries from GET /api/v1/threads. */
export interface ThreadListResponse {
  items: ThreadSummary[];
  total: number;
  limit: number;
  offset: number;
}

/** Single LLM completion record from fin_agents.llm_responses. */
export interface LlmResponseRecord {
  id: number;
  event_id: string;
  ts: string;
  provider: string;
  model: string;
  task_key: string | null;
  node_name: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  latency_ms: number;
  thinking: string | null;
  answer: string | null;
}

/** LLM completion records for a thread from GET /api/v1/threads/{thread_id}/llm-responses. */
export interface LlmResponseList {
  thread_id: string;
  records: LlmResponseRecord[];
}

/** LangGraph checkpoint state from GET /api/v1/threads/{thread_id}/state. */
export interface ThreadStateResponse {
  thread_id: string;
  checkpoint_id: string | null;
  /** Raw LangGraph state dict; empty object when no checkpoint exists yet. */
  state: Record<string, unknown>;
}

/** Request body for POST /api/v1/threads/{thread_id}/status. */
export interface UpdateThreadStatusRequest {
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  error?: string | null;
  emit_event?: boolean;
}

/** Response from POST /api/v1/threads/{thread_id}/status. */
export interface UpdateThreadStatusResponse {
  thread_id: string;
  status: string;
  event_emitted: boolean;
}

/** Request body for POST /api/v1/threads/{thread_id}/events/emit. */
export interface EmitEventRequest {
  event: string;
  payload?: Record<string, unknown>;
}

/** Response from POST /api/v1/threads/{thread_id}/events/emit. */
export interface EmitEventResponse {
  thread_id: string;
  event: string;
  published: boolean;
}

/** Response from POST /api/v1/threads/{thread_id}/events/resync. */
export interface ResyncResponse {
  thread_id: string;
  events_emitted: number;
}
