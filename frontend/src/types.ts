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
  report?: StrategyReport;
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

/** Full strategy report — mirrors fin_strategies.reports with reference tasks. */
export interface StrategyReport {
  id: number;
  symbol: string;
  short_term_technical_desc: string;
  long_term_technical_desc: string;
  news_desc: string;
  basic_biz_desc: string;
  industry_desc: string;
  significant_event_desc: string | null;
  short_term_risk_desc: string | null;
  long_term_risk_desc: string | null;
  short_term_growth_desc: string | null;
  long_term_growth_desc: string | null;
  recent_trade_anomalies: string | null;
  likely_today_fall_desc: string | null;
  likely_tom_fall_desc: string | null;
  likely_short_term_fall_desc: string | null;
  likely_long_term_fall_desc: string | null;
  likely_today_rise_desc: string | null;
  likely_tom_rise_desc: string | null;
  likely_short_term_rise_desc: string | null;
  likely_long_term_rise_desc: string | null;
  last_quote_quant_stats_id: number | null;
  market_data_task_ids: number[] | null;
  created_at: string;
  reference_tasks: TaskInfo[];
}
