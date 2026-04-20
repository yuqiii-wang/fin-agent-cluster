import type { GuestUser, ThreadSummary } from "../types";
import { BASE } from "./config";

// ── Guest auth ───────────────────────────────────────────────────────────────

const GUEST_TOKEN_KEY = "fin_guest_token";
const GUEST_USERNAME_KEY = "fin_guest_username";

export function getStoredToken(): string | null {
  return localStorage.getItem(GUEST_TOKEN_KEY);
}

export function getStoredUsername(): string | null {
  return localStorage.getItem(GUEST_USERNAME_KEY);
}

export async function guestLogin(token: string | null): Promise<GuestUser> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["X-User-Token"] = token;
  const res = await fetch(`${BASE}/auth/guest`, { method: "POST", headers });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const user: GuestUser = await res.json();
  localStorage.setItem(GUEST_TOKEN_KEY, user.id);
  localStorage.setItem(GUEST_USERNAME_KEY, user.username);
  return user;
}

export async function fetchActiveThread(token: string): Promise<ThreadSummary | null> {
  const res = await fetch(`${BASE}/auth/me/active`, {
    headers: { "X-User-Token": token },
  });
  if (!res.ok) return null;
  const data = await res.json();
  return data ?? null;
}

export async function fetchHistory(token: string, limit = 20): Promise<ThreadSummary[]> {
  const res = await fetch(`${BASE}/auth/me/history?limit=${limit}`, {
    headers: { "X-User-Token": token },
  });
  if (!res.ok) return [];
  return res.json();
}
