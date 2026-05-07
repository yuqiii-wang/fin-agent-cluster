import { Tag } from "antd";
import { CheckCircleFilled, CloseCircleFilled, MinusCircleFilled, SyncOutlined } from "@ant-design/icons";
import type { GraphNode, GraphTask } from "../types";

export function fmtElapsed(ms?: number): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function nodeStatusTag(status: GraphNode["status"]) {
  switch (status) {
    case "pending":   return <Tag color="default">Pending</Tag>;
    case "running":   return <Tag icon={<SyncOutlined spin />} color="processing">Running</Tag>;
    case "completed": return <Tag icon={<CheckCircleFilled />} color="success">Completed</Tag>;
    case "failed":    return <Tag icon={<CloseCircleFilled />} color="error">Failed</Tag>;
    case "cancelled": return <Tag icon={<MinusCircleFilled />} color="warning">Cancelled</Tag>;
    case "paused":    return <Tag color="warning">Paused</Tag>;
  }
}

export function taskStatusTag(status: GraphTask["status"]) {
  switch (status) {
    case "pending":   return <Tag color="default">Pending</Tag>;
    case "running":   return <Tag icon={<SyncOutlined spin />} color="processing">Running</Tag>;
    case "completed": return <Tag icon={<CheckCircleFilled />} color="success">Completed</Tag>;
    case "failed":    return <Tag icon={<CloseCircleFilled />} color="error">Failed</Tag>;
    case "cancelled": return <Tag icon={<MinusCircleFilled />} color="warning">Cancelled</Tag>;
  }
}
