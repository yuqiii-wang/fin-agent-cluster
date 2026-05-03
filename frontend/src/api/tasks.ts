import type { TaskTypeMeta } from "../types";
import { BASE } from "./config";

// ── Tasks ────────────────────────────────────────────────────────────────────

/** Cancel a running task by UUID — sends cancel signal via task control channel. */
export async function cancelTask(taskId: string): Promise<void> {
  const res = await fetch(`${BASE}/tasks/${taskId}/cancel`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as Record<string, string>).detail ?? `HTTP ${res.status}`);
  }
}

/** Pass (accept partial output) a running streaming task by UUID. */
export async function passTask(taskId: string): Promise<void> {
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
