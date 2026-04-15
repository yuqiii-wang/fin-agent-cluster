/** API helpers. All paths are proxied through vite to localhost:8432. */
import type { NodeExecutionInfo, QuantIndicatorMeta, QuantIndicatorSeries, QueryResponse, SessionStatus, StrategyReport, TaskTypeMeta, CurrencyInfo } from "./types";

const BASE = "/api/v1";

export async function submitQuery(
  query: string
): Promise<QueryResponse> {
  const res = await fetch(`${BASE}/users/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
    onDone?: (data: unknown) => void;
    onClose?: () => void;
  }
): () => void {
  const es = new EventSource(`/api/v1/stream/${threadId}`);

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
  es.addEventListener("done", (e: MessageEvent) =>
    handlers.onDone?.(parse(e.data))
  );
  es.onerror = () => {
    es.close();
    handlers.onClose?.();
  };

  return () => es.close();
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
