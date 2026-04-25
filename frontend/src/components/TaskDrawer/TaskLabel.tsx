import { Flex, Space, Tag, Typography } from "antd";
import { LoadingOutlined } from "@ant-design/icons";
import type { TaskInfo } from "../../types";
import { styles } from "./TaskLabel.styles";

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
    <Flex align="center" gap={8} style={styles.container}>
      <Text strong style={styles.labelText}>
        {task.task_key}
      </Text>
      <Tag color={STATUS_COLOR[task.status] ?? "default"} style={styles.statusTag}>
        {task.status === "running" ? (
          <Space size={4}><LoadingOutlined />{task.status}</Space>
        ) : task.status}
      </Tag>
    </Flex>
  );
}
