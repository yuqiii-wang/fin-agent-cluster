import { useEffect, useState } from "react";
import { guestLogin, getStoredToken } from "../api";

export interface GuestAuthState {
  /** UUID bearer token — pass as X-User-Token on every request. */
  token: string | null;
  username: string | null;
  /** True while the initial auth call is in flight. */
  loading: boolean;
}

/**
 * Manages guest authentication persisted to localStorage.
 *
 * On first render it calls POST /auth/guest (with no token) to create a fresh
 * guest account.  On subsequent renders it re-validates the stored token; if
 * the server doesn't recognise it a new account is created transparently.
 */
export function useGuestAuth(): GuestAuthState {
  const [token, setToken] = useState<string | null>(getStoredToken);
  const [username, setUsername] = useState<string | null>(
    () => localStorage.getItem("fin_guest_username")
  );
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const storedToken = getStoredToken();
    guestLogin(storedToken)
      .then((user) => {
        setToken(user.id);
        setUsername(user.username);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  return { token, username, loading };
}
