import { useEffect, useRef, useState } from "react";
import { Flex, Spin, Steps, Tooltip, Typography } from "antd";
import type { NodeExecutionInfo, NodeGroup } from "../types";
import { fetchNodeExecutions } from "../api";
import { JsonViewer } from "./JsonViewer";
import { NODE_LABELS } from "./nodeLabels";

const { Text } = Typography;

const STEP_STATUS: Record<NodeGroup["status"], "wait" | "process" | "finish" | "error"> = {
  pending: "wait",
  running: "process",
  completed: "finish",
  failed: "error",
};

interface Props {
  nodes: NodeGroup[];
  threadId: string;
  onNodeClick: (node: NodeGroup) => void;
  tokenStreams?: Record<number, string>;
}

/** Field with label + JsonViewer (copy button is built into JsonViewer). */
function LabelledField({ label, data }: { label: string; data: unknown }) {
  return (
    <div>
      <Text type="secondary" style={{ fontSize: 11, fontWeight: 600 }}>{label}</Text>
      <JsonViewer data={data} maxHeight={400} />
    </div>
  );
}

/** Inline input/output panel for a node, showing the actual state data. */
function NodeInlinePanel({ execution }: { execution: NodeExecutionInfo | null | "loading" }) {
  if (execution === "loading") {
    return <Flex justify="center" style={{ marginTop: 8 }}><Spin size="small" /></Flex>;
  }

  return (
    <Flex vertical gap={6} style={{ marginTop: 8 }}>
      <div>
        {execution ? (
          <LabelledField label="Input" data={execution.input} />
        ) : (
          <>
            <Text type="secondary" style={{ fontSize: 11, fontWeight: 600 }}>Input</Text>
            <div>—</div>
          </>
        )}
      </div>
      <div>
        {execution ? (
          <LabelledField label="Output" data={execution.output} />
        ) : (
          <>
            <Text type="secondary" style={{ fontSize: 11, fontWeight: 600 }}>Output</Text>
            <div>—</div>
          </>
        )}
      </div>
    </Flex>
  );
}

/** Visual pipeline using antd Steps — click a node to show its input/output below. */
export function NodeList({ nodes, threadId, onNodeClick, tokenStreams: _tokenStreams = {} }: Props) {
  const [selectedNodeName, setSelectedNodeName] = useState<string | null>(null);
  const [executions, setExecutions] = useState<Record<string, NodeExecutionInfo | null>>({});
  const [loading, setLoading] = useState(false);
  const prevStatusRef = useRef<Record<string, string>>({});

  /** Re-fetch execution data for the selected node when it transitions to completed. */
  useEffect(() => {
    let needsRefresh = false;
    for (const node of nodes) {
      const prev = prevStatusRef.current[node.node_name];
      if (
        prev !== undefined &&
        prev !== "completed" &&
        node.status === "completed" &&
        node.node_name === selectedNodeName
      ) {
        needsRefresh = true;
      }
      prevStatusRef.current[node.node_name] = node.status;
    }
    if (!needsRefresh || !selectedNodeName) return;

    console.debug("[NodeList] auto-refresh executions selectedNode=%s threadId=%s", selectedNodeName, threadId);
    setLoading(true);
    fetchNodeExecutions(threadId)
      .then((list) => {
        console.debug("[NodeList] auto-refresh ok count=%d", list.length);
        const map: Record<string, NodeExecutionInfo | null> = {};
        for (const e of list) map[e.node_name] = e;
        setExecutions(map);
      })
      .catch((err) => {
        console.error("[NodeList] auto-refresh fetchNodeExecutions failed", err);
      })
      .finally(() => setLoading(false));
  }, [nodes, selectedNodeName, threadId]);

  const handleClick = (node: NodeGroup) => {
    const name = node.node_name;
    console.debug("[NodeList] click node=%s status=%s threadId=%s", name, node.status, threadId);
    if (selectedNodeName === name) {
      setSelectedNodeName(null);
      return;
    }
    setSelectedNodeName(name);
    onNodeClick(node);

    // Fetch if not cached, or if we have a stale entry with empty output for a completed node
    const cached = executions[name];
    const stale = cached !== undefined && node.status === "completed" &&
      Object.keys(cached?.output ?? {}).length === 0;

    console.debug("[NodeList] cached=%o stale=%s", cached, stale);
    if (!(name in executions) || stale) {
      setLoading(true);
      console.debug("[NodeList] fetching executions threadId=%s", threadId);
      fetchNodeExecutions(threadId)
        .then((list) => {
          console.debug("[NodeList] fetchNodeExecutions ok count=%d", list.length, list);
          const map: Record<string, NodeExecutionInfo | null> = {};
          for (const e of list) map[e.node_name] = e;
          setExecutions(map);
        })
        .catch((err) => {
          console.error("[NodeList] fetchNodeExecutions failed", err);
          setExecutions((prev) => ({ ...prev, [name]: null }));
        })
        .finally(() => setLoading(false));
    }
  };

  const items = nodes.map((node) => ({
    onClick: () => handleClick(node),
    style: { cursor: "pointer" },
    title: (
      <Tooltip title={`${node.tasks.length} task(s) — click to inspect`}>
        <span style={{ fontSize: 12 }}>{NODE_LABELS[node.node_name] ?? node.node_name}</span>
      </Tooltip>
    ),
    description: <span style={{ fontSize: 11 }}>{node.tasks.length} task(s)</span>,
    status: STEP_STATUS[node.status],
  }));

  const panelData: NodeExecutionInfo | null | "loading" =
    selectedNodeName === null
      ? null
      : loading
      ? "loading"
      : executions[selectedNodeName] ?? null;

  return (
    <>
      <Steps
        size="small"
        direction="horizontal"
        responsive={false}
        style={{ marginTop: 8 }}
        items={items}
      />
      {selectedNodeName !== null && (
        <NodeInlinePanel execution={panelData} />
      )}
    </>
  );
}

