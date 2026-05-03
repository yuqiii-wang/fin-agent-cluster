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

export function isLlmTask(taskName: string, meta: { llm_task_names: string[] }): boolean {
  return meta.llm_task_names.includes(taskName);
}

export function isPerfTokenTask(taskName: string, meta: { perf_token_task_names: string[] }): boolean {
  return meta.perf_token_task_names.includes(taskName);
}

/** Human-readable running description derived directly from the task key. */
export function taskRunningLabel(taskName: string): string {
  return taskName.replace(/_/g, " ") + "…";
}
