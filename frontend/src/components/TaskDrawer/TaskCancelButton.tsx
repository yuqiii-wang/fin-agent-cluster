import { Button, Tooltip } from "antd";
import { StopOutlined } from "@ant-design/icons";
import { useState } from "react";
import type { TaskInfo } from "../../types";
import { cancelTask } from "../../api";

/**
 * Cancel button shown in the task collapse header for every running task.
 *
 * Calls POST /tasks/{task_id}/cancel which:
 *  1. Signals the LLM stream loop to stop and marks this task as cancelled.
 *  2. The task returns an empty output so the LangGraph node continues
 *     gathering results from other tasks and the query proceeds.
 *
 * This is NOT a query-level cancel. To stop the entire query use the query cancel button.
 */
export function TaskCancelButton({ task }: { task: TaskInfo }) {
  const [busy, setBusy] = useState(false);

  const handleCancel = async (e: React.MouseEvent) => {
    // Stop propagation so the click does not toggle the Collapse panel.
    e.stopPropagation();
    setBusy(true);
    try {
      await cancelTask(task.id);
    } catch (err) {
      console.error("[TaskCancelButton] cancel failed", err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Tooltip title="Cancel this task's LLM stream. The task returns an empty result and the query continues.">
      <Button
        size="small"
        danger
        loading={busy}
        icon={<StopOutlined />}
        onClick={handleCancel}
        style={{ fontSize: 11 }}
      >
        Cancel
      </Button>
    </Tooltip>
  );
}
