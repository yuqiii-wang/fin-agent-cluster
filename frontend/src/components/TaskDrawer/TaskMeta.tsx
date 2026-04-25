import { Descriptions, Flex, Tooltip, Typography } from "antd";
import { CopyOutlined } from "@ant-design/icons";
import type { TaskInfo } from "../../types";
import { styles } from "./TaskMeta.styles";

const { Text } = Typography;

export function TaskMeta({ task }: { task: TaskInfo }) {
  return (
    <Descriptions
      size="small"
      column={1}
      bordered
      styles={{
        label: { fontSize: 11, whiteSpace: "nowrap", width: 72 },
        content: { fontSize: 11 },
      }}
      items={[
        {
          key: "thread",
          label: "thread",
          children: (
            <Tooltip title={task.thread_id}>
                <Flex align="center" gap={4} style={styles.threadFlex}>
                <Text
                  code
                  style={styles.threadCode}
                >
                  {task.thread_id}
                </Text>
                <CopyOutlined
                  style={styles.copyIcon}
                  onClick={() => navigator.clipboard.writeText(task.thread_id)}
                />
              </Flex>
            </Tooltip>
          ),
        },
        {
          key: "node",
          label: "node",
          children: <Text code style={styles.codeText}>{task.node_name}</Text>,
        },
        {
          key: "task_key",
          label: "task_key",
          children: <Text code style={styles.codeText}>{task.task_key}</Text>,
        },
        {
          key: "id",
          label: "id",
          children: <Text code style={styles.codeText}>{task.id}</Text>,
        },
      ]}
    />
  );
}
