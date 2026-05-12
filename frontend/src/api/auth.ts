/**
 * Auth API client.
 * Guest token is stored in localStorage under 'fin_user_token'.
 */

import type { GuestAuthResponse } from '../types';

const BASE = '/api/v1';

export function getStoredToken(): string | null {
  return localStorage.getItem('fin_user_token');
}

export function setStoredToken(token: string): void {
  localStorage.setItem('fin_user_token', token);
}

export function clearStoredToken(): void {
  localStorage.removeItem('fin_user_token');
}

export async function ensureGuest(): Promise<GuestAuthResponse> {
  const existing = getStoredToken();
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (existing) headers['X-User-Token'] = existing;

  const res = await fetch(`${BASE}/auth/guest`, { method: 'POST', headers });
  if (!res.ok) throw new Error(`Guest auth failed: ${res.status}`);
  const data: GuestAuthResponse = await res.json();
  setStoredToken(data.id);
  return data;
}

export async function getSsePresenceToken(): Promise<import('../types').CentrifugoTokenResponse> {
  const token = getStoredToken();
  if (!token) throw new Error('No user token');
  const res = await fetch(`${BASE}/auth/centrifugo/sse-presence`, {
    headers: { 'X-User-Token': token },
  });
  if (!res.ok) throw new Error(`sse-presence token failed: ${res.status}`);
  return res.json();
}
