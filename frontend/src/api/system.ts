/**
 * System API client.
 * Endpoints: GET /api/v1/system/settings
 */

export interface LlmProviderSettings {
  provider: string;
  model: string;
}

export interface ServerSettingsResponse {
  llm: LlmProviderSettings;
}

/** Fetch current server settings (no auth required). */
export async function fetchServerSettings(): Promise<ServerSettingsResponse> {
  const res = await fetch('/api/v1/system/settings');
  if (!res.ok) throw new Error(`Failed to fetch server settings: ${res.status}`);
  return res.json();
}
