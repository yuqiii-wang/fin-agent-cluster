import {
  Collapse,
  Descriptions,
  Drawer,
  Dropdown,
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
  QuestionCircleOutlined,
} from "@ant-design/icons";
import { useEffect, useRef, useState } from "react";
import type { NodeGroup, TaskInfo, TaskTypeMeta } from "../types";
import { NODE_LABELS } from "./nodeLabels";
import { JsonViewer } from "./JsonViewer";
import { OutputViewer, isLlmTask } from "./OutputViewer";
import { watchTask, cancelTask, passTask } from "../api";


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
      styles={{ label: { fontSize: 11, whiteSpace: "nowrap", width: 72 }, content: { fontSize: 11 } }}
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

const ACTIONS_HELP = (
  <div style={{ maxWidth: 260 }}>
    <p style={{ margin: "0 0 6px" }}>
      <strong>Cancel</strong> — stops the LLM stream immediately and marks this task as
      <em> cancelled</em>. Downstream tasks that depend on its output will be skipped.
    </p>
    <p style={{ margin: 0 }}>
      <strong>Pass</strong> — stops the stream and accepts whatever the LLM has generated so
      far as the final output. The partial JSON is used to populate the required output schema.
    </p>
  </div>
);

/** Dropdown action button shown on running LLM tasks. */
function LlmTaskActions({ task }: { task: TaskInfo }) {
  const [busy, setBusy] = useState(false);

  const handleAction = async (action: "cancel" | "pass") => {
    setBusy(true);
    try {
      if (action === "cancel") {
        await cancelTask(task.id);
      } else {
        await passTask(task.id);
      }
    } catch (err) {
      console.error("[LlmTaskActions] action failed", err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Flex align="center" gap={6}>
      <Dropdown
        disabled={busy}
        menu={{
          items: [
            {
              key: "cancel",
              label: "Cancel",
              danger: true,
              onClick: () => handleAction("cancel"),
            },
            {
              key: "pass",
              label: "Pass",
              onClick: () => handleAction("pass"),
            },
          ],
        }}
        trigger={["click"]}
      >
        <a
          onClick={(e) => e.preventDefault()}
          style={{ fontSize: 11, userSelect: "none" }}
        >
          <Space size={4}>
            {busy ? <LoadingOutlined style={{ fontSize: 11 }} /> : null}
            Actions
            <DownOutlined style={{ fontSize: 9 }} />
          </Space>
        </a>
      </Dropdown>
      <Tooltip title={ACTIONS_HELP} placement="rightTop">
        <QuestionCircleOutlined style={{ fontSize: 12, color: "var(--ant-color-text-quaternary)", cursor: "help" }} />
      </Tooltip>
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

  // Accordion: a single string key, or undefined when all collapsed.
  // Initialise to the first running task so live output is visible on open.
  const [activeKey, setActiveKey] = useState<string | undefined>(
    () => node?.tasks.find((t) => t.status === "running")?.id.toString()
  );

  // Reset the expanded panel whenever the drawer switches to a different node.
  const prevNodeNameRef = useRef<string | undefined>(node?.node_name);
  useEffect(() => {
    if (node?.node_name === prevNodeNameRef.current) return;
    prevNodeNameRef.current = node?.node_name;
    setActiveKey(node?.tasks.find((t) => t.status === "running")?.id.toString());
  }, [node]);

  // threadId is stable for the lifetime of a task group — use the first task's id.
  const threadId = node?.tasks[0]?.thread_id ?? "";

  // Register the active task with the backend watch registry whenever it changes,
  // including on initial open — so tokens start flowing as soon as the drawer opens.
  useEffect(() => {
    if (!threadId || activeKey === undefined) return;
    const taskId = parseInt(activeKey, 10);
    console.debug("[TaskDrawer] watchTask threadId=%s taskId=%d", threadId, taskId);
    watchTask(threadId, taskId).catch((err) => {
      console.error("[TaskDrawer] watchTask failed", err);
    });
  }, [threadId, activeKey]);

  const handleCollapseChange = (keys: string | string[]) => {
    const arr = (Array.isArray(keys) ? keys : [keys]).filter(Boolean);
    // If the active panel was clicked again, collapse it; otherwise switch to the new one.
    const next = arr.find((k) => k !== activeKey);
    console.debug("[TaskDrawer] collapseChange keys=%o activeKey=%s next=%s", arr, activeKey, next);
    setActiveKey(next);
    // watchTask is handled by the useEffect above on activeKey change
  };

  const handleClose = () => {
    console.debug("[TaskDrawer] close threadId=%s", threadId);
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
            // Show the actions button only on the actively-expanded task that is
            // still running AND is an LLM stream (tokens flowing or meta confirms it).
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
