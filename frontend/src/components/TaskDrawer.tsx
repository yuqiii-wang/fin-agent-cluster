import {
  Button,
  Collapse,
  Descriptions,
  Drawer,
  Flex,
  Space,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import {
  ClockCircleOutlined,
  CopyOutlined,
  DownOutlined,
  LoadingOutlined,
  UpOutlined,
} from "@ant-design/icons";
import { useMemo, useState } from "react";
import type { NodeGroup, TaskInfo, TaskTypeMeta } from "../types";
import { NODE_LABELS } from "./NodeList";
import { JsonViewer } from "./JsonViewer";
import { OutputViewer } from "./OutputViewer";


const { Text } = Typography;

const STATUS_COLOR: Record<string, string> = {
  completed: "success",
  running: "processing",
  failed: "error",
  pending: "default",
  cancelled: "warning",
};

/** Metadata grid for a single task using antd Descriptions. */
function TaskMeta({ task }: { task: TaskInfo }) {
  return (
    <Descriptions
      size="small"
      column={1}
      bordered
      labelStyle={{ fontSize: 11, whiteSpace: "nowrap", width: 72 }}
      contentStyle={{ fontSize: 11 }}
      items={[
        {
          key: "thread",
          label: "thread",
          children: (
            <Tooltip title={task.thread_id}>
              <Flex align="center" gap={4} style={{ minWidth: 0 }}>
                <Text
                  code
                  style={{
                    fontSize: 11,
                    maxWidth: 200,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    display: "inline-block",
                  }}
                >
                  {task.thread_id}
                </Text>
                <CopyOutlined
                  style={{ fontSize: 10, cursor: "pointer", flexShrink: 0 }}
                  onClick={() => navigator.clipboard.writeText(task.thread_id)}
                />
              </Flex>
            </Tooltip>
          ),
        },
        {
          key: "node",
          label: "node",
          children: <Text code style={{ fontSize: 11 }}>{task.node_name}</Text>,
        },
        {
          key: "task_key",
          label: "task_key",
          children: <Text code style={{ fontSize: 11 }}>{task.task_key}</Text>,
        },
        {
          key: "id",
          label: "id",
          children: <Text code style={{ fontSize: 11 }}>{task.id}</Text>,
        },
      ]}
    />
  );
}

/** Collapse panel header: task key + status badge. */
function TaskLabel({ task }: { task: TaskInfo }) {
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

interface Props {
  node: NodeGroup | null;
  /** Accumulated token strings keyed by task id, for live streaming display. */
  tokenStreams: Record<number, string>;
  /** LLM provider name keyed by task id, from the started SSE event. */
  taskProviders: Record<number, string>;
  /** Task type metadata from the backend (drives OutputViewer routing). */
  taskMeta: TaskTypeMeta | null;
  onClose: () => void;
}

export function TaskDrawer({ node, tokenStreams, taskProviders, taskMeta, onClose }: Props) {
  const title = node
    ? `${NODE_LABELS[node.node_name] ?? node.node_name} — Tasks`
    : "Tasks";

  const defaultOpenKeys = useMemo(
    () => node?.tasks.filter((t) => t.status === "running").map((t) => String(t.id)) ?? [],
    [node],
  );

  const [activeKeys, setActiveKeys] = useState<string[]>(defaultOpenKeys);
  const allKeys = node?.tasks.map((t) => String(t.id)) ?? [];
  const allExpanded = allKeys.length > 0 && allKeys.every((k) => activeKeys.includes(k));

  return (
    <Drawer
      title={title}
      placement="right"
      width="50vw"
      open={node !== null}
      onClose={onClose}
      styles={{ body: { padding: "12px 8px" } }}
    >
      {node && (
        <Flex vertical gap={8}>
          {/* ── Top bar ── */}
          <Flex justify="flex-end">
            <Tooltip title={allExpanded ? "Collapse all" : "Expand all"}>
              <Button
                size="small"
                icon={allExpanded ? <UpOutlined /> : <DownOutlined />}
                onClick={() => setActiveKeys(allExpanded ? [] : allKeys)}
              >
                {allExpanded ? "Collapse all" : "Expand all"}
              </Button>
            </Tooltip>
          </Flex>

          {/* ── Task panels ── */}
          <Collapse
            activeKey={activeKeys}
            onChange={(keys) => setActiveKeys(Array.isArray(keys) ? keys : [keys as string])}
            size="small"
            style={{ background: "transparent", border: "none" }}
            items={node.tasks.map((task) => {
              const stream = tokenStreams[task.id];
              const hasInput = task.input && Object.keys(task.input).length > 0;

              return {
                key: String(task.id),
                label: <TaskLabel task={task} />,
                style: { marginBottom: 6, borderRadius: 6 },
                children: (
                  <Flex vertical gap={8}>
                    {/* Metadata grid */}
                    <TaskMeta task={task} />

                    {/* Input section */}
                    {hasInput && (
                      <Flex vertical gap={4}>
                        <Text type="secondary" style={{ fontSize: 11, fontWeight: 500 }}>INPUT</Text>
                        <JsonViewer data={task.input} maxHeight={300} />
                      </Flex>
                    )}

                    {/* Output section — routed through OutputViewer */}
                    <Flex vertical gap={4}>
                      <Text type="secondary" style={{ fontSize: 11, fontWeight: 500 }}>OUTPUT</Text>
                      <OutputViewer
                        task={task}
                        stream={stream}
                        provider={taskProviders[task.id]}
                        taskMeta={taskMeta}
                      />
                    </Flex>

                    {/* Timing */}
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
        </Flex>
      )}
    </Drawer>
  );
}
