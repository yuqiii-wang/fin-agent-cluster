/**
 * AuthContext — provides current user identity across the app.
 *
 * On mount the context attempts to restore / create a guest session using the
 * token stored in localStorage.  If a registered user token is stored instead,
 * the same ``/auth/guest`` endpoint will revalidate it and return the existing
 * account, so no separate login path is needed at the API level.
 */

import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { ensureGuest, getStoredToken, setStoredToken, clearStoredToken } from '../api/auth';
import type { GuestAuthResponse } from '../types';

export interface AuthUser extends GuestAuthResponse {}

interface AuthContextValue {
  user: AuthUser | null;
  /** True while the initial session check is in flight. */
  loading: boolean;
  /** Refresh / create the session (also called after explicit login). */
  refresh: () => Promise<void>;
  /** Log out: clears token and resets to null until next refresh. */
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  loading: true,
  refresh: async () => {},
  logout: () => {},
});

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const data = await ensureGuest();
      setUser(data);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(() => {
    clearStoredToken();
    setUser(null);
  }, []);

  useEffect(() => {
    // On mount, restore session if a token is already stored.
    const token = getStoredToken();
    if (token) {
      refresh();
    } else {
      setLoading(false);
    }
  }, [refresh]);

  return (
    <AuthContext.Provider value={{ user, loading, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export function useAuth(): AuthContextValue {
  return useContext(AuthContext);
}
