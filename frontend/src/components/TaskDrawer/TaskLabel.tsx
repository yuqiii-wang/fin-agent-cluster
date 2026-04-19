import { Flex, Space, Tag, Typography } from "antd";
import { LoadingOutlined } from "@ant-design/icons";
import type { TaskInfo } from "../../types";

const { Text } = Typography;

export const STATUS_COLOR: Record<string, string> = {
  completed: "success",
  running:   "processing",
  failed:    "error",
  pending:   "default",
  cancelled: "warning",
};

export function TaskLabel({ task }: { task: TaskInfo }) {
  return (
    <Flex align="center" gap={8} style={{ width: "100%", minWidth: 0 }}>
      <Text strong style={{ fontSize: 13, flex: 1, minWidth: 0 }}>
        {task.task_key}
      </Text>
      <Tag color={STATUS_COLOR[task.status] ?? "default"} style={{ marginRight: 0, flexShrink: 0 }}>
        {task.status === "running" ? (
          <Space size={4}><LoadingOutlined />{task.status}</Space>
        ) : task.status}
      </Tag>
    </Flex>
  );
}
