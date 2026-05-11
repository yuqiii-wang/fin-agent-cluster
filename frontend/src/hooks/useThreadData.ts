/**
 * useThreadData — poll nodes and tasks after SSE events trigger a refresh.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { getNodes, getTasks, getThread } from '../api/threads';
import type { NodeInfo, QueryResponse, TaskInfo } from '../types';

interface ThreadData {
  thread: QueryResponse | null;
  nodes: NodeInfo[];
  tasks: TaskInfo[];
  refresh: () => void;
}

const TERMINAL = new Set(['completed', 'failed', 'cancelled']);

export function useThreadData(threadId: string): ThreadData {
  const [thread, setThread] = useState<QueryResponse | null>(null);
  const [nodes, setNodes] = useState<NodeInfo[]>([]);
  const [tasks, setTasks] = useState<TaskInfo[]>([]);
  const pendingRef = useRef(false);

  const refresh = useCallback(() => {
    if (pendingRef.current) return;
    pendingRef.current = true;
    Promise.all([getThread(threadId), getNodes(threadId), getTasks(threadId)])
      .then(([t, n, k]) => {
        setThread(t);
        setNodes(n);
        setTasks(k);
      })
      .catch(() => {/* ignore transient errors */})
      .finally(() => { pendingRef.current = false; });
  }, [threadId]);

  // Initial load
  useEffect(() => {
    refresh();
  }, [refresh]);

  return { thread, nodes, tasks, refresh };
}
