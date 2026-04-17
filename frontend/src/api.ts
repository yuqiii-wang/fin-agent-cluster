/** API helpers. All paths route through Kong API Gateway.
 *  Dev: Vite proxy forwards to Kong at localhost:8888.
 *  Prod: set VITE_KONG_URL=http://<host>:8888 at build time.
 */
import type { GuestUser, NodeExecutionInfo, QuantIndicatorMeta, QuantIndicatorSeries, QueryResponse, SessionStatus, StrategyReport, TaskTypeMeta, ThreadSummary, CurrencyInfo } from "./types";

// Base origin for Kong. Empty string in dev (Vite proxy), absolute URL in prod.
const KONG_ORIGIN: string = (import.meta.env.VITE_KONG_URL as string | undefined) ?? "";
const BASE = `${KONG_ORIGIN}/api/v1`;

// ── Guest auth ───────────────────────────────────────────────────────────────

const GUEST_TOKEN_KEY = "fin_guest_token";
const GUEST_USERNAME_KEY = "fin_guest_username";

export function getStoredToken(): string | null {
  return localStorage.getItem(GUEST_TOKEN_KEY);
}

export function getStoredUsername(): string | null {
  return localStorage.getItem(GUEST_USERNAME_KEY);
}

export async function guestLogin(token: string | null): Promise<GuestUser> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["X-User-Token"] = token;
  const res = await fetch(`${BASE}/auth/guest`, { method: "POST", headers });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const user: GuestUser = await res.json();
  localStorage.setItem(GUEST_TOKEN_KEY, user.id);
  localStorage.setItem(GUEST_USERNAME_KEY, user.username);
  return user;
}

export async function fetchActiveThread(token: string): Promise<ThreadSummary | null> {
  const res = await fetch(`${BASE}/auth/me/active`, {
    headers: { "X-User-Token": token },
  });
  if (!res.ok) return null;
  const data = await res.json();
  return data ?? null;
}

export async function fetchHistory(token: string, limit = 20): Promise<ThreadSummary[]> {
  const res = await fetch(`${BASE}/auth/me/history?limit=${limit}`, {
    headers: { "X-User-Token": token },
  });
  if (!res.ok) return [];
  return res.json();
}

// ── Queries ──────────────────────────────────────────────────────────────────

export async function submitQuery(
  query: string,
  token: string,
): Promise<QueryResponse> {
  const res = await fetch(`${BASE}/users/query`, {
    method: "POST",
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

export async function fetchNodeExecutions(threadId: string): Promise<NodeExecutionInfo[]> {
  const res = await fetch(`${BASE}/users/query/${threadId}/nodes`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function cancelQuery(threadId: string): Promise<void> {
  const res = await fetch(`${BASE}/users/query/${threadId}/cancel`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
}

/** Open an SSE stream for a thread, invoking callbacks on each event.
 *  Returns a cleanup function that closes the connection. */
export function openStream(
  threadId: string,
  handlers: {
    onStarted?: (data: unknown) => void;
    onToken?: (data: unknown) => void;
    onCompleted?: (data: unknown) => void;
    onFailed?: (data: unknown) => void;
    onCancelled?: (data: unknown) => void;
    onDone?: (data: unknown) => void;
    onClose?: () => void;
  }
): () => void {
  const es = new EventSource(`${KONG_ORIGIN}/api/v1/stream/${threadId}`);
  // Prevent onClose from firing more than once (e.g. error then explicit close).
  let closed = false;
  const notifyClose = () => {
    if (closed) return;
    closed = true;
    handlers.onClose?.();
  };

  const parse = (raw: string): unknown => {
    try { return JSON.parse(raw); } catch { return {}; }
  };

  es.addEventListener("started", (e: MessageEvent) =>
    handlers.onStarted?.(parse(e.data))
  );
  es.addEventListener("token", (e: MessageEvent) =>
    handlers.onToken?.(parse(e.data))
  );
  es.addEventListener("completed", (e: MessageEvent) =>
    handlers.onCompleted?.(parse(e.data))
  );
  es.addEventListener("failed", (e: MessageEvent) =>
    handlers.onFailed?.(parse(e.data))
  );
  es.addEventListener("cancelled", (e: MessageEvent) =>
    handlers.onCancelled?.(parse(e.data))
  );
  es.addEventListener("done", (e: MessageEvent) =>
    handlers.onDone?.(parse(e.data))
  );
  // EventSource.CLOSED = 2; only treat a persistent error as a real drop.
  // Transient errors (CONNECTING = 0) are browser-managed retries — ignore them.
  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) {
      notifyClose();
    }
    // readyState === CONNECTING means browser is auto-retrying — do nothing.
  };

  return () => {
    es.close();
    notifyClose();
  };
}

/** Register the task the client currently has expanded in the TaskDrawer.
 *  Passing null unwatches (panel collapsed / drawer closed).
 *  The SSE stream will then suppress token events for tasks not being watched. */
export async function watchTask(threadId: string, taskId: number | null): Promise<void> {
  await fetch(`${BASE}/stream/${encodeURIComponent(threadId)}/watch`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_id: taskId }),
  });
}

/** Cancel a running LLM task — marks it as cancelled and stops streaming. */
export async function cancelTask(taskId: number): Promise<void> {
  const res = await fetch(`${BASE}/tasks/${taskId}/cancel`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as Record<string, string>).detail ?? `HTTP ${res.status}`);
  }
}

/** Pass a running LLM task — stops streaming and accepts partial output as final result. */
export async function passTask(taskId: number): Promise<void> {
  const res = await fetch(`${BASE}/tasks/${taskId}/pass`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as Record<string, string>).detail ?? `HTTP ${res.status}`);
  }
}

export async function fetchLatestReport(symbol: string): Promise<StrategyReport> {
  const res = await fetch(`${BASE}/reports/symbol/${encodeURIComponent(symbol)}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export async function fetchReportById(reportId: number): Promise<StrategyReport> {
  const res = await fetch(`${BASE}/reports/${reportId}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

/** Fetch the static list of available technical indicators from the backend. */
export async function fetchQuantIndicators(): Promise<QuantIndicatorMeta[]> {
  const res = await fetch(`${BASE}/quant/indicators`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/** Fetch a single indicator time-series for a given symbol and granularity.
 *  One call per indicator — no bulk fetching. */
export async function fetchQuantStat(
  symbol: string,
  granularity: string,
  indicator: string,
  instrumentType = "equity",
): Promise<QuantIndicatorSeries> {
  const params = new URLSearchParams({ indicator, instrument_type: instrumentType });
  const res = await fetch(
    `${BASE}/quant/stats/${encodeURIComponent(symbol)}/${encodeURIComponent(granularity)}?${params}`,
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

/** Fetch currency info for a symbol (ISO 4217 code, name, display symbol, decimals).
 *  Returns null when the symbol has no region/currency data in the DB. */
export async function fetchSymbolCurrency(symbol: string): Promise<CurrencyInfo | null> {
  const res = await fetch(`${BASE}/quant/symbol-currency/${encodeURIComponent(symbol)}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function fetchTaskMeta(): Promise<TaskTypeMeta> {
  const res = await fetch(`${BASE}/tasks/meta`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
