/** LLM provider display name map. */
export const PROVIDER_LABELS: Record<string, string> = {
  ark: "Doubao/ARK",
  gemini: "Gemini",
  ollama: "Ollama (local)",
};

export function providerLabel(provider?: string): string {
  if (!provider) return "LLM";
  return PROVIDER_LABELS[provider] ?? provider;
}

export function isLlmTask(taskKey: string, meta: { llm_task_keys: string[] }): boolean {
  return meta.llm_task_keys.includes(taskKey);
}

export function isPerfTokenTask(taskKey: string, meta: { perf_token_task_keys: string[] }): boolean {
  return meta.perf_token_task_keys.includes(taskKey);
}

/** Human-readable running description derived directly from the task key. */
export function taskRunningLabel(taskKey: string): string {
  return taskKey.replace(/_/g, " ") + "…";
}
