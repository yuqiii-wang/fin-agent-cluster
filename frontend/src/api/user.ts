/**
 * User preferences API client.
 * Endpoints: GET/PUT /api/v1/users/me/preferences
 */

import { getStoredToken } from './auth';
import type { NodeConfig, UserPreference, UserPreferencesResponse } from '../types';

const BASE = '/api/v1/users/me';

function authHeaders(): Record<string, string> {
  const token = getStoredToken();
  if (!token) throw new Error('No user token');
  return { 'Content-Type': 'application/json', 'X-User-Token': token };
}

/** Fetch all preferences for the authenticated user. */
export async function fetchPreferences(): Promise<UserPreferencesResponse> {
  const res = await fetch(`${BASE}/preferences`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Failed to fetch preferences: ${res.status}`);
  return res.json();
}

/** Upsert preferences for a single node. */
export async function upsertPreference(
  nodeName: string,
  config: NodeConfig,
): Promise<UserPreference> {
  const res = await fetch(`${BASE}/preferences/${encodeURIComponent(nodeName)}`, {
    method: 'PUT',
    headers: authHeaders(),
    body: JSON.stringify({ config }),
  });
  if (!res.ok) throw new Error(`Failed to save preference: ${res.status}`);
  return res.json();
}
