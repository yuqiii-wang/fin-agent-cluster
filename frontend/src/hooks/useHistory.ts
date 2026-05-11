/**
 * useHistory — fetches the current user's thread history from the backend.
 *
 * Automatically re-fetches when the user identity changes and exposes a
 * ``prepend`` helper so freshly submitted threads appear at the top without
 * a full network round-trip.
 */

import { useCallback, useEffect, useState } from 'react';
import { getHistory } from '../api/threads';
import { getStoredToken } from '../api/auth';
import type { ThreadSummary } from '../types';

interface UseHistoryResult {
  history: ThreadSummary[];
  /** Prepend a new entry (after a successful query submission). */
  prepend: (entry: ThreadSummary) => void;
  /** Re-fetch from the backend (e.g., after a status change). */
  reload: () => Promise<void>;
}

export function useHistory(userId: string | undefined): UseHistoryResult {
  const [history, setHistory] = useState<ThreadSummary[]>([]);

  const reload = useCallback(async () => {
    if (!userId || !getStoredToken()) return;
    try {
      const data = await getHistory();
      setHistory(data);
    } catch {
      // silently ignore — user may not be authenticated yet
    }
  }, [userId]);

  useEffect(() => {
    setHistory([]);
    reload();
  }, [reload]);

  const prepend = useCallback((entry: ThreadSummary) => {
    setHistory((prev) => {
      // Avoid duplicate if reload() already picked it up.
      if (prev.some((t) => t.thread_id === entry.thread_id)) return prev;
      return [entry, ...prev];
    });
  }, []);

  return { history, prepend, reload };
}
