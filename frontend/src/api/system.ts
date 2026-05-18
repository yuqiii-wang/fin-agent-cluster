/**
 * System API client — wraps /api/v1/system/* calls.
 */

import { getStoredToken } from './auth';

const BASE = '/api/v1';

function authHeaders(): Record<string, string> {
  const token = getStoredToken();
  return {
    'Content-Type': 'application/json',
    ...(token ? { 'X-User-Token': token } : {}),
  };
}

export interface SystemConfig {
  test_mode: boolean;
}

export async function fetchSystemConfig(): Promise<SystemConfig> {
  const res = await fetch(`${BASE}/system/config`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`System config fetch failed: ${res.status}`);
  return res.json();
}
