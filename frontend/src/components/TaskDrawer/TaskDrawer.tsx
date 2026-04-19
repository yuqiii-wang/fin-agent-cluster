import { Collapse, Drawer, Flex, Space, Typography } from "antd";
import { ClockCircleOutlined } from "@ant-design/icons";
import { useEffect, useRef, useState } from "react";
import type { NodeGroup, TaskTypeMeta } from "../../types";
import { NODE_LABELS } from "../nodeLabels";
import { JsonViewer } from "../JsonViewer";
import { OutputViewer, isLlmTask } from "../OutputViewer";
import { watchTask } from "../../api";
import { TaskMeta } from "./TaskMeta";
import { TaskLabel } from "./TaskLabel";
import { LlmTaskActions } from "./LlmTaskActions";

const { Text } = Typography;

interface Props {
  node: NodeGroup | null;
  tokenStreams: Record<number, string>;
  taskProviders: Record<number, string>;
  taskMeta: TaskTypeMeta | null;
  onClose: () => void;
}

export function TaskDrawer({ node, tokenStreams, taskProviders, taskMeta, onClose }: Props) {
  const title = node
    ? `${NODE_LABELS[node.node_name] ?? node.node_name} — Tasks`
    : "Tasks";

  const [activeKey, setActiveKey] = useState<string | undefined>(
    () => node?.tasks.find((t) => t.status === "running")?.id.toString()
  );

  const prevNodeNameRef = useRef<string | undefined>(node?.node_name);
  useEffect(() => {
    if (node?.node_name === prevNodeNameRef.current) return;
    prevNodeNameRef.current = node?.node_name;
    setActiveKey(node?.tasks.find((t) => t.status === "running")?.id.toString());
  }, [node]);

  const threadId = node?.tasks[0]?.thread_id ?? "";

  useEffect(() => {
    if (!threadId || activeKey === undefined) return;
    const taskId = parseInt(activeKey, 10);
    watchTask(threadId, taskId).catch((err) => {
      console.error("[TaskDrawer] watchTask failed", err);
    });
  }, [threadId, activeKey]);

  const handleCollapseChange = (keys: string | string[]) => {
    const arr = (Array.isArray(keys) ? keys : [keys]).filter(Boolean);
    const next = arr.find((k) => k !== activeKey);
    setActiveKey(next);
  };

  const handleClose = () => {
    if (threadId) watchTask(threadId, null).catch((err) => console.error("[TaskDrawer] unwatch failed", err));
    onClose();
  };

  return (
    <Drawer
      title={title}
      placement="right"
      width="50vw"
      open={node !== null}
      onClose={handleClose}
      styles={{ body: { padding: "12px 8px" } }}
    >
      {node && (
        <Collapse
          accordion
          activeKey={activeKey !== undefined ? [activeKey] : []}
          onChange={handleCollapseChange}
          size="small"
          style={{ background: "transparent", border: "none" }}
          items={node.tasks.map((task) => {
            const stream = tokenStreams[task.id];
            const hasInput = task.input && Object.keys(task.input).length > 0;
            const isLlmRunning =
              activeKey === String(task.id) &&
              task.status === "running" &&
              (!!stream || (taskMeta != null && isLlmTask(task.task_key, taskMeta)));

            return {
              key: String(task.id),
              label: <TaskLabel task={task} />,
              style: { marginBottom: 6, borderRadius: 6 },
              children: (
                <Flex vertical gap={8}>
                  <TaskMeta task={task} />

                  {hasInput && (
                    <Flex vertical gap={4}>
                      <Text type="secondary" style={{ fontSize: 11, fontWeight: 500 }}>INPUT</Text>
                      <JsonViewer data={task.input} maxHeight={300} />
                    </Flex>
                  )}

                  <Flex vertical gap={4}>
                    <Flex align="center" justify="space-between">
                      <Text type="secondary" style={{ fontSize: 11, fontWeight: 500 }}>OUTPUT</Text>
                      {isLlmRunning && <LlmTaskActions task={task} />}
                    </Flex>
                    <OutputViewer
                      task={task}
                      stream={stream}
                      provider={taskProviders[task.id]}
                      taskMeta={taskMeta}
                    />
                  </Flex>

                  <Space size={16}>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      <ClockCircleOutlined style={{ marginRight: 4 }} />
                      started {new Date(task.created_at).toLocaleTimeString()}
                    </Text>
                    {task.status !== "running" && (
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        updated {new Date(task.updated_at).toLocaleTimeString()}
                      </Text>
                    )}
                  </Space>
                </Flex>
              ),
            };
          })}
        />
      )}
    </Drawer>
  );
}
