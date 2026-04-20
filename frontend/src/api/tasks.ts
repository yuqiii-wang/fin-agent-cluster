import type { TaskTypeMeta } from "../types";
import { BASE } from "./config";

// ── Tasks ────────────────────────────────────────────────────────────────────

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

export async function fetchTaskMeta(): Promise<TaskTypeMeta> {
  const res = await fetch(`${BASE}/tasks/meta`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
