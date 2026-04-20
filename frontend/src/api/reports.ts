import type { StrategyReport } from "../types";
import { BASE } from "./config";

// ── Reports ──────────────────────────────────────────────────────────────────

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
