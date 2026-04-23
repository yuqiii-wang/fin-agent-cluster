import { useEffect, useState } from "react";
import { fetchTasks } from "../../api";
import { TaskDrawer } from "../TaskDrawer";
import type { NodeGroup, TaskInfo, TaskTypeMeta } from "../../types";

interface Props {
  /** Thread ID whose tasks to display, or null when closed. */
  threadId: string | null;
  taskMeta: TaskTypeMeta | null;
  onClose: () => void;
}

function groupByNode(tasks: TaskInfo[]): NodeGroup | null {
  if (tasks.length === 0) return null;
  const grouped = new Map<string, NodeGroup>();
  for (const task of tasks) {
    const existing = grouped.get(task.node_name);
    if (!existing) {
      grouped.set(task.node_name, { node_name: task.node_name, status: task.status, tasks: [task] });
    } else {
      existing.tasks.push(task);
      // Escalate status: running > failed > cancelled > completed
      if (task.status === "running") existing.status = "running";
      else if (task.status === "failed" && existing.status !== "running") existing.status = "failed";
    }
  }
  // Perf test graph has a single "perf_test_streamer" node; return the first group.
  return [...grouped.values()][0] ?? null;
}

/**
 * Drawer that fetches tasks fresh from the backend for a given perf-test
 * stream thread_id and renders them via {@link TaskDrawer}.
 *
 * Opened by clicking the "Tasks" button on a row in the perf test grid.
 * Token streaming is not wired here — perf tasks use ``perf_token`` events
 * which are not reflected in the TaskDrawer's live output viewer.
 */
export function StreamTaskDrawer({ threadId, taskMeta, onClose }: Props) {
  const [nodeGroup, setNodeGroup] = useState<NodeGroup | null>(null);

  useEffect(() => {
    if (!threadId) {
      setNodeGroup(null);
      return;
    }
    fetchTasks(threadId)
      .then((status) => setNodeGroup(groupByNode(status.tasks)))
      .catch((err) => console.error("[StreamTaskDrawer] fetchTasks failed", err));
  }, [threadId]);

  return (
    <TaskDrawer
      node={nodeGroup}
      tokenStreams={{}}
      taskProviders={{}}
      taskMeta={taskMeta}
      onClose={onClose}
    />
  );
}
